"""App Blocker — Phase 1: kill blocked processes on a 1s tick.

Hardcoded test rule:
  - macOS:   Calculator (open it, watch it die)
  - Windows: Notepad    (open it, watch it die)

Stdlib only. Run with:

    python main.py     (Windows)
    python3 main.py    (macOS)
"""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk


BLOCKED_NAMES = {"Calculator", "Notepad", "Notepad.exe"}
TICK_INTERVAL = 1.0

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _normalize(name: str) -> str:
    n = name.strip().lower()
    if n.endswith(".exe"):
        n = n[:-4]
    return n


BLOCKED_NORMALIZED = {_normalize(n) for n in BLOCKED_NAMES}


def list_processes() -> tuple[list[tuple[int, str]], str]:
    """Return ([(pid, name), ...], method_used)."""
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None

    if psutil is not None:
        procs = [
            (p.info["pid"], p.info["name"])
            for p in psutil.process_iter(["pid", "name"])
            if p.info.get("name")
        ]
        return procs, "psutil"

    if sys.platform == "win32":
        return _list_windows_tasklist(), "tasklist"
    return _list_unix_ps(), "ps"


def _list_windows_tasklist() -> list[tuple[int, str]]:
    out = subprocess.check_output(
        ["tasklist", "/FO", "CSV", "/NH"],
        text=True,
        creationflags=CREATE_NO_WINDOW,
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


class KillerThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._kill_count = 0
        self._last_killed: list[str] = []
        self._last_tick_at: float = 0.0
        self._method: str = ""

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            tick_start = time.monotonic()
            killed: list[str] = []
            method = self._method
            try:
                procs, method = list_processes()
                for pid, name in procs:
                    if _normalize(name) in BLOCKED_NORMALIZED:
                        if kill_pid(pid):
                            killed.append(f"{name} (pid {pid})")
            except Exception as exc:
                killed.append(f"<error: {exc!r}>")

            with self._lock:
                self._last_tick_at = time.monotonic()
                self._method = method
                if killed:
                    self._kill_count += len([k for k in killed if not k.startswith("<error")])
                    self._last_killed = killed

            elapsed = time.monotonic() - tick_start
            self._stop.wait(max(0.0, TICK_INTERVAL - elapsed))

    def snapshot(self) -> tuple[int, list[str], float, str]:
        with self._lock:
            return self._kill_count, list(self._last_killed), self._last_tick_at, self._method


def main() -> None:
    killer = KillerThread()
    killer.start()
    started_at = time.monotonic()

    root = tk.Tk()
    root.title("App Blocker — Phase 1")
    root.geometry("580x440")

    def on_close() -> None:
        killer.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    banner = tk.Frame(root, bg="#b00020", height=44)
    banner.pack(fill=tk.X)
    tk.Label(
        banner,
        text=" Blocking active (Phase 1 hardcoded test rule)",
        fg="white",
        bg="#b00020",
        font=("TkDefaultFont", 11, "bold"),
        anchor="w",
    ).pack(fill=tk.X, padx=12, pady=10)

    body = ttk.Frame(root, padding=12)
    body.pack(fill=tk.BOTH, expand=True)

    ttk.Label(body, text="Test rule — these process names are killed on every 1s tick:").pack(anchor="w")
    ttk.Label(
        body,
        text=", ".join(sorted(BLOCKED_NAMES)),
        foreground="#444",
        font=("TkFixedFont", 11),
    ).pack(anchor="w", pady=(0, 12))

    ttk.Label(body, text="Try it:").pack(anchor="w")
    instructions = (
        "  • macOS: open Calculator.app — should die within ~1 second\n"
        "  • Windows: open Notepad — should die within ~1 second"
    )
    ttk.Label(body, text=instructions, foreground="#444").pack(anchor="w", pady=(0, 12))

    ttk.Separator(body, orient="horizontal").pack(fill=tk.X, pady=6)

    status_var = tk.StringVar(value="Killer thread starting…")
    ttk.Label(body, textvariable=status_var, font=("TkDefaultFont", 11)).pack(anchor="w", pady=(8, 0))

    last_var = tk.StringVar(value="")
    ttk.Label(body, textvariable=last_var, foreground="#0a7", wraplength=540).pack(anchor="w", pady=(4, 0))

    info_var = tk.StringVar(
        value=f"Python {sys.version.split()[0]} on {platform.system()} {platform.release()}"
    )
    ttk.Label(body, textvariable=info_var, foreground="#888").pack(anchor="w", pady=(12, 0))

    def refresh() -> None:
        kills, last_killed, last_tick_at, method = killer.snapshot()
        uptime = time.monotonic() - started_at
        if last_tick_at == 0:
            status_var.set("Killer thread starting…")
        else:
            ago = max(0.0, time.monotonic() - last_tick_at)
            status_var.set(
                f"Kills since launch: {kills}  |  enum method: {method}  |  "
                f"last tick {ago:.1f}s ago  |  uptime {uptime:.0f}s"
            )
        if last_killed:
            last_var.set("Recently killed: " + ", ".join(last_killed))
        root.after(500, refresh)

    refresh()
    root.mainloop()


if __name__ == "__main__":
    main()
