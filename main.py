"""App Blocker — Phase 2: schedule-driven blocking with persistent config.

Config lives at ~/.app-blocker/config.json. On first run a demo config is written
that blocks Notepad / Calculator at all times so it's easy to verify. Edit
config.json to customize; changes are picked up on the next tick (~1s).

Run:
    python main.py     (Windows)
    python3 main.py    (macOS)
"""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, time as dt_time
from pathlib import Path
from tkinter import ttk


TICK_INTERVAL = 1.0
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES = {
    "mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu",
    "fri": "Fri", "sat": "Sat", "sun": "Sun",
}


DEFAULT_CONFIG: dict = {
    "_README": (
        "Edit this file to customize. Saved changes are picked up within ~1 second. "
        "Schedule windows are HH:MM 24h local time. Day keys: mon, tue, wed, thu, fri, sat, sun. "
        "To block all day, use a single window 00:00-23:59. To never block on a day, use [] for that day."
    ),
    "blockedApps": [
        {
            "id": "demo-1",
            "displayName": "Demo: Notepad / Calculator",
            "matchers": {"names": ["Notepad", "Notepad.exe", "Calculator"]},
        }
    ],
    "schedule": {
        "mon": [{"start": "00:00", "end": "23:59"}],
        "tue": [{"start": "00:00", "end": "23:59"}],
        "wed": [{"start": "00:00", "end": "23:59"}],
        "thu": [{"start": "00:00", "end": "23:59"}],
        "fri": [{"start": "00:00", "end": "23:59"}],
        "sat": [{"start": "00:00", "end": "23:59"}],
        "sun": [{"start": "00:00", "end": "23:59"}],
    },
    "settings": {
        "breakDurationMinutes": 10,
        "cooldownMinutes": 30,
        "challengeWordCount": 50,
    },
}


# ---------------------------------------------------------------------------
# Config / paths
# ---------------------------------------------------------------------------

def app_data_dir() -> Path:
    return Path.home() / ".app-blocker"


def config_path() -> Path:
    return app_data_dir() / "config.json"


def load_or_create_config() -> dict:
    path = config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        return json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Schedule logic
# ---------------------------------------------------------------------------

def _parse_hhmm(s: str) -> dt_time:
    h, m = s.split(":")
    return dt_time(int(h), int(m))


def active_window(now: datetime, schedule: dict) -> dict | None:
    """Return the currently-active window dict, or None."""
    day_key = DAY_KEYS[now.weekday()]
    now_t = now.time()
    for w in schedule.get(day_key, []):
        try:
            start = _parse_hhmm(w["start"])
            end = _parse_hhmm(w["end"])
        except (KeyError, ValueError):
            continue
        if start <= now_t <= end:
            return w
    return None


def _normalize(name: str) -> str:
    n = name.strip().lower()
    if n.endswith(".exe"):
        n = n[:-4]
    return n


def collect_blocked_normalized(blocked_apps: list[dict]) -> set[str]:
    out: set[str] = set()
    for app in blocked_apps:
        for n in app.get("matchers", {}).get("names", []):
            out.add(_normalize(n))
    return out


# ---------------------------------------------------------------------------
# Process enumeration & kill (psutil with stdlib fallback)
# ---------------------------------------------------------------------------

def list_processes() -> tuple[list[tuple[int, str]], str]:
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None

    if psutil is not None:
        return (
            [
                (p.info["pid"], p.info["name"])
                for p in psutil.process_iter(["pid", "name"])
                if p.info.get("name")
            ],
            "psutil",
        )
    if sys.platform == "win32":
        return _list_windows_tasklist(), "tasklist"
    return _list_unix_ps(), "ps"


def _list_windows_tasklist() -> list[tuple[int, str]]:
    out = subprocess.check_output(
        ["tasklist", "/FO", "CSV", "/NH"], text=True, creationflags=CREATE_NO_WINDOW
    )
    result: list[tuple[int, str]] = []
    for line in out.splitlines():
        parts = line.split('","')
        if len(parts) < 2:
            continue
        name = parts[0].lstrip('"')
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        if name:
            result.append((pid, name))
    return result


def _list_unix_ps() -> list[tuple[int, str]]:
    out = subprocess.check_output(["ps", "-axco", "pid,command"], text=True)
    result: list[tuple[int, str]] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        result.append((pid, parts[1]))
    return result


def kill_pid(pid: int) -> bool:
    try:
        import psutil  # type: ignore

        psutil.Process(pid).kill()
        return True
    except ImportError:
        pass
    except Exception:
        return False
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                check=True,
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )
            return True
        except subprocess.CalledProcessError:
            return False
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Killer thread
# ---------------------------------------------------------------------------

class KillerThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._kill_count = 0
        self._last_killed: list[str] = []
        self._last_tick_at: float = 0.0
        self._method: str = ""
        self._config: dict = {}
        self._config_mtime: float = 0.0
        self._config_error: str = ""
        self._active_window: dict | None = None
        self._reload_config(force=True)

    def stop(self) -> None:
        self._stop.set()

    def _reload_config(self, force: bool = False) -> None:
        path = config_path()
        try:
            if not path.exists():
                self._config = load_or_create_config()
                self._config_mtime = path.stat().st_mtime
                self._config_error = ""
                return
            mtime = path.stat().st_mtime
            if force or mtime != self._config_mtime:
                self._config = json.loads(path.read_text())
                self._config_mtime = mtime
                self._config_error = ""
        except Exception as e:
            self._config_error = f"{type(e).__name__}: {e}"

    def run(self) -> None:
        while not self._stop.is_set():
            tick_start = time.monotonic()
            killed: list[str] = []
            method = self._method
            self._reload_config()

            now = datetime.now()
            window = active_window(now, self._config.get("schedule", {}))
            blocked_normalized = collect_blocked_normalized(
                self._config.get("blockedApps", [])
            )

            if window and blocked_normalized:
                try:
                    procs, method = list_processes()
                    for pid, name in procs:
                        if _normalize(name) in blocked_normalized:
                            if kill_pid(pid):
                                killed.append(f"{name} (pid {pid})")
                except Exception as exc:
                    killed.append(f"<error: {exc!r}>")

            with self._lock:
                self._last_tick_at = time.monotonic()
                self._method = method
                self._active_window = window
                if killed:
                    self._kill_count += sum(1 for k in killed if not k.startswith("<error"))
                    self._last_killed = killed

            elapsed = time.monotonic() - tick_start
            self._stop.wait(max(0.0, TICK_INTERVAL - elapsed))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "kills": self._kill_count,
                "last_killed": list(self._last_killed),
                "last_tick_at": self._last_tick_at,
                "method": self._method,
                "config": self._config,
                "config_error": self._config_error,
                "active_window": dict(self._active_window) if self._active_window else None,
            }


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def _summarize_blocked(config: dict) -> str:
    apps = config.get("blockedApps", [])
    if not apps:
        return "(no apps configured)"
    names = []
    for app in apps:
        names.extend(app.get("matchers", {}).get("names", []))
    return ", ".join(names) if names else "(no matchers)"


def _summarize_schedule_today(schedule: dict, now: datetime) -> str:
    day_key = DAY_KEYS[now.weekday()]
    windows = schedule.get(day_key, [])
    if not windows:
        return f"{DAY_NAMES[day_key]}: no windows"
    parts = [f"{w.get('start','?')}–{w.get('end','?')}" for w in windows]
    return f"{DAY_NAMES[day_key]}: " + ", ".join(parts)


def main() -> None:
    # Ensure config exists before launching UI
    load_or_create_config()

    killer = KillerThread()
    killer.start()
    started_at = time.monotonic()

    root = tk.Tk()
    root.title("App Blocker")
    root.geometry("620x500")

    def on_close() -> None:
        killer.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    banner = tk.Frame(root, bg="#888", height=44)
    banner.pack(fill=tk.X)
    banner_label = tk.Label(
        banner, text="", fg="white", bg="#888",
        font=("TkDefaultFont", 11, "bold"), anchor="w",
    )
    banner_label.pack(fill=tk.X, padx=12, pady=10)

    body = ttk.Frame(root, padding=12)
    body.pack(fill=tk.BOTH, expand=True)

    config_path_var = tk.StringVar(value=f"Config: {config_path()}")
    ttk.Label(body, textvariable=config_path_var, foreground="#666",
              font=("TkFixedFont", 10)).pack(anchor="w")
    ttk.Label(body, text="(Edit that file to customize. Changes apply within ~1 second.)",
              foreground="#888").pack(anchor="w", pady=(0, 12))

    ttk.Separator(body, orient="horizontal").pack(fill=tk.X, pady=4)

    today_var = tk.StringVar(value="")
    ttk.Label(body, text="Today's schedule:").pack(anchor="w", pady=(8, 0))
    ttk.Label(body, textvariable=today_var, foreground="#222",
              font=("TkFixedFont", 11)).pack(anchor="w")

    blocked_var = tk.StringVar(value="")
    ttk.Label(body, text="Blocked apps:").pack(anchor="w", pady=(8, 0))
    ttk.Label(body, textvariable=blocked_var, foreground="#222",
              font=("TkFixedFont", 11), wraplength=580, justify="left").pack(anchor="w")

    ttk.Separator(body, orient="horizontal").pack(fill=tk.X, pady=10)

    status_var = tk.StringVar(value="Killer thread starting…")
    ttk.Label(body, textvariable=status_var, font=("TkDefaultFont", 11)).pack(anchor="w")

    last_var = tk.StringVar(value="")
    ttk.Label(body, textvariable=last_var, foreground="#0a7",
              wraplength=580, justify="left").pack(anchor="w", pady=(4, 0))

    error_var = tk.StringVar(value="")
    ttk.Label(body, textvariable=error_var, foreground="#b00020",
              wraplength=580, justify="left").pack(anchor="w", pady=(4, 0))

    info_var = tk.StringVar(value=(
        f"Python {sys.version.split()[0]} on {platform.system()} {platform.release()}"
    ))
    ttk.Label(body, textvariable=info_var, foreground="#888").pack(anchor="w", pady=(12, 0))

    def refresh() -> None:
        snap = killer.snapshot()
        cfg = snap["config"]
        window = snap["active_window"]
        now = datetime.now()

        if window:
            banner.config(bg="#b00020")
            banner_label.config(
                bg="#b00020",
                text=f"  Blocking active until {window.get('end','?')} "
                     f"(window {window.get('start','?')}–{window.get('end','?')})",
            )
        else:
            banner.config(bg="#888")
            banner_label.config(bg="#888", text="  No active block")

        today_var.set(_summarize_schedule_today(cfg.get("schedule", {}), now))
        blocked_var.set(_summarize_blocked(cfg))

        kills = snap["kills"]
        last_tick = snap["last_tick_at"]
        method = snap["method"] or "(none yet)"
        uptime = time.monotonic() - started_at
        if last_tick == 0:
            status_var.set("Killer thread starting…")
        else:
            ago = max(0.0, time.monotonic() - last_tick)
            status_var.set(
                f"Kills since launch: {kills}  |  enum: {method}  |  "
                f"last tick {ago:.1f}s ago  |  uptime {uptime:.0f}s"
            )

        last_killed = snap["last_killed"]
        last_var.set("Recently killed: " + ", ".join(last_killed) if last_killed else "")

        err = snap["config_error"]
        error_var.set(f"Config error: {err}" if err else "")

        root.after(500, refresh)

    refresh()
    root.mainloop()


if __name__ == "__main__":
    main()
