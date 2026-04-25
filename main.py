"""App Blocker — Phase 4: schedule + word-challenge allowance break.

Config:    ~/.app-blocker/config.json   (user-editable)
State:     ~/.app-blocker/state.json    (managed by app — current break, last
                                         break end for cooldown)
Wordlist:  words.txt next to this file

Run:
    python main.py     (Windows)
    python3 main.py    (macOS)
"""

from __future__ import annotations

import json
import os
import platform
import random
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from tkinter import messagebox, ttk


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

DEFAULT_STATE: dict = {
    "currentBreak": None,
    "lastBreakEndedAt": None,
}


# ---------------------------------------------------------------------------
# Paths & file I/O
# ---------------------------------------------------------------------------

def app_data_dir() -> Path:
    return Path.home() / ".app-blocker"


def config_path() -> Path:
    return app_data_dir() / "config.json"


def state_path() -> Path:
    return app_data_dir() / "state.json"


def words_path() -> Path:
    return Path(__file__).resolve().parent / "words.txt"


def load_or_create_config() -> dict:
    path = config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        return json.loads(json.dumps(DEFAULT_CONFIG))
    return json.loads(path.read_text())


def load_state() -> dict:
    path = state_path()
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_STATE))
    try:
        return json.loads(path.read_text())
    except Exception:
        return json.loads(json.dumps(DEFAULT_STATE))


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


_FALLBACK_WORDS = (
    "about above across action active actual adopt after again agent agree "
    "ahead alarm alert alike alive allow alone along alpha alter among anger "
    "angle angry apart apple apply argue arise arrow aside audio avoid awake "
    "award aware basic basin batch beach bench black blade blame blank blast "
    "bleed blend bless blind blink block blood bloom blown board boost booth "
    "bound brain brake brand brave bread break brick brief bring broad broke "
    "brown brush build built bunch burst buyer cabin cable candy carry catch "
    "chain chair chalk charm chart chase check cheer chess chest chief child "
    "civil claim class clean clear clerk click cliff climb clock close cloth "
    "cloud coach coast color cover craft crash cream creek crest crime crisp "
    "cross crowd crown crude cruel crush cycle daily dance death debit debut "
    "delay delta demon dense depth dirty diver dizzy dough dozen drain drama "
    "dream dress drink drive drove drown drunk eagle early earth eaten echo "
    "eight elbow elder elect empty enemy enjoy enter entry equal error event "
    "every exact exist extra fable faint faith false fancy fatal fault favor "
    "fence ferry fetch fever fiber field fifth fifty fight final first fixed "
    "flame flash fleet flesh flint float flock flood floor flour flute focus "
    "force forge forth forty forum found frame fraud fresh front frost fruit "
    "funny ghost giant given glare glass gleam glide globe gloom glory glove "
    "going grace grade grain grand grant grape graph grasp grass grave great "
    "greed green greet grief grill grind gross group grown grunt guard guess "
    "guest guide guild habit happy heart heavy hedge hello hover human humor "
    "hurry ideal image index inner input issue ivory jelly jewel joint juice "
    "kayak knack knife knock known label large laser later laugh lazy learn "
    "least leave legal lemon level light limit linen liver lobby local logic "
    "loose loyal lunar lunch magic major maple march match maybe mayor medal "
    "media metal meter might minor mixed model moist money month moral mount "
    "mouse mouth movie nasty nerve never night noble noise north novel ocean "
    "offer often olive onion opera orbit order ought ounce outer owner paint "
    "panel panic paper party patch peace pearl penny phase photo piano piece "
    "pilot pizza plane plant plate plaza poem point polar porch pouch pound "
    "power press price pride prime print prior prize proof proud pulse punch "
    "purse quart queen quest queue quick quiet quilt quirk quite quote radar "
    "radio rapid ratio reach react ready realm relay reply reset resin ridge "
    "rigid rinse rival river roast rocky rough round royal rusty sadly salad "
    "sandy sauce scale scarf scene scent scout scrap scrub seven shake shall "
    "shape share sharp sheep sheet shelf shell shift shine shiny shirt shock "
    "short shout shown shrub sight silly since sixth skate skill slate sleep "
    "slept slice slide slope small smart smell smile smoke smoky snack snake "
    "snore snowy solid solve sorry sound south spade spare spark speak speed "
    "spell spend spent spice spike spine spoke spoon sport spray stack staff "
    "stage stair stamp stand stark state steam steel steep stern stick still "
    "sting stock stone stool storm story stove straw strip stuck study stuff "
    "style sugar sweep sweet swift swing table tally taste teach teeth tempo "
    "tenor tense thank theft their theme there thick thief thigh thing think "
    "third thorn those three threw throw thumb tidal tight tiger timer tired "
    "toast today token tooth topic torch total touch tough tower toxic trace "
    "track trade trail train trait trash treat trend trial tribe trick tried "
    "troop trout truck truly trunk trust truth tulip tutor twice twist ultra "
    "uncle under unite unity until upper upset urban usage usual vague valid "
    "value vapor vault verge verse video viola vital vivid vocal voice vowel "
    "wagon waltz water waver wedge weigh weird whale wharf wheat wheel whirl "
    "white whole wider witch woven wrist write wrong yacht yeast yield young "
    "youth zebra"
).split()


def load_wordlist() -> tuple[list[str], str]:
    """Return (words, source_description). Tries words.txt next to the script
    and in cwd; otherwise returns the embedded fallback.
    """
    candidates = [
        Path(__file__).resolve().parent / "words.txt",
        Path.cwd() / "words.txt",
    ]
    for p in candidates:
        try:
            text = p.read_text()
        except OSError:
            continue
        words = [w.strip().lower() for w in text.splitlines() if w.strip()]
        if len(words) >= 50:
            return words, f"file: {p}"
    return list(_FALLBACK_WORDS), f"embedded ({len(_FALLBACK_WORDS)} words)"


# ---------------------------------------------------------------------------
# Schedule logic
# ---------------------------------------------------------------------------

def _parse_hhmm(s: str) -> dt_time:
    h, m = s.split(":")
    return dt_time(int(h), int(m))


def active_window(now: datetime, schedule: dict) -> dict | None:
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
# Process enumeration & kill
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
# Killer thread (with break / cooldown state)
# ---------------------------------------------------------------------------

def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


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
        self._state: dict = load_state()
        self._reload_config(force=True)

    def stop(self) -> None:
        self._stop.set()

    # -- config --

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

    # -- break / cooldown (state.json-backed) --

    def _settings(self) -> dict:
        return self._config.get("settings", {}) or {}

    def break_duration(self) -> float:
        return float(self._settings().get("breakDurationMinutes", 10))

    def cooldown_duration(self) -> float:
        return float(self._settings().get("cooldownMinutes", 30))

    def is_break_active(self) -> bool:
        """Returns True if a break is currently active. Lazily ends expired breaks."""
        with self._lock:
            cb = self._state.get("currentBreak")
            if not cb:
                return False
            ends_at = _parse_iso(cb.get("endsAt"))
            if ends_at is None or datetime.now() >= ends_at:
                # Break ended — finalize cooldown
                self._state["currentBreak"] = None
                self._state["lastBreakEndedAt"] = datetime.now().isoformat()
                save_state(self._state)
                return False
            return True

    def break_ends_at(self) -> datetime | None:
        with self._lock:
            cb = self._state.get("currentBreak")
            if not cb:
                return None
            return _parse_iso(cb.get("endsAt"))

    def cooldown_remaining_seconds(self) -> float:
        last = _parse_iso(self._state.get("lastBreakEndedAt"))
        if last is None:
            return 0.0
        elapsed = (datetime.now() - last).total_seconds()
        cd = self.cooldown_duration() * 60.0
        return max(0.0, cd - elapsed)

    def can_take_break(self) -> tuple[bool, str]:
        if self._active_window is None:
            return False, "No active block — break has nothing to unblock"
        if self.is_break_active():
            return False, "Break already active"
        cd = self.cooldown_remaining_seconds()
        if cd > 0:
            mins = int(cd // 60)
            secs = int(cd % 60)
            return False, f"Cooldown: {mins}m {secs}s remaining"
        return True, ""

    def start_break(self) -> None:
        with self._lock:
            now = datetime.now()
            ends = now + timedelta(minutes=self.break_duration())
            self._state["currentBreak"] = {
                "startedAt": now.isoformat(),
                "endsAt": ends.isoformat(),
            }
            save_state(self._state)

    def reset_break_state(self) -> None:
        with self._lock:
            self._state = {"currentBreak": None, "lastBreakEndedAt": None}
            save_state(self._state)

    # -- main loop --

    def run(self) -> None:
        while not self._stop.is_set():
            tick_start = time.monotonic()
            killed: list[str] = []
            method = self._method
            self._reload_config()

            now = datetime.now()
            window = active_window(now, self._config.get("schedule", {}))

            # Lazily expire any active break (writes lastBreakEndedAt on expiry).
            break_active = self.is_break_active()

            blocked_normalized = collect_blocked_normalized(
                self._config.get("blockedApps", [])
            )

            if window and blocked_normalized and not break_active:
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
                "state": dict(self._state),
            }


# ---------------------------------------------------------------------------
# Word challenge modal
# ---------------------------------------------------------------------------

class ChallengeModal:
    def __init__(self, parent: tk.Tk, words: list[str], on_complete) -> None:
        self.words = words
        self.idx = 0
        self.on_complete = on_complete
        self._completed = False

        self.win = tk.Toplevel(parent)
        self.win.title("Allowance break — type to unlock")
        self.win.geometry("680x420")
        self.win.transient(parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)

        header = ttk.Frame(self.win, padding=(16, 16, 16, 8))
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=f"Type these {len(words)} words to start a break.",
            font=("TkDefaultFont", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="Press space (or enter) after each word. Typos make you retype the current word.",
            foreground="#666",
        ).pack(anchor="w", pady=(2, 0))

        text_frame = ttk.Frame(self.win, padding=(16, 0, 16, 0))
        text_frame.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(
            text_frame, wrap=tk.WORD, height=8, font=("TkDefaultFont", 14),
            relief="flat", borderwidth=1, highlightthickness=1, highlightbackground="#ccc",
        )
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.tag_configure("done", foreground="#aaa")
        self.text.tag_configure("current", background="#fff3a0")
        self.text.tag_configure("pending", foreground="#222")
        self._render_words()
        self.text.config(state=tk.DISABLED)

        bottom = ttk.Frame(self.win, padding=(16, 8, 16, 16))
        bottom.pack(fill=tk.X)

        self.progress_var = tk.StringVar(value=self._progress_text())
        ttk.Label(bottom, textvariable=self.progress_var, font=("TkDefaultFont", 11)).pack(anchor="w")

        self.entry = tk.Entry(bottom, font=("TkDefaultFont", 14))
        self.entry.pack(fill=tk.X, pady=(8, 8))
        self.entry.bind("<space>", self._on_separator)
        self.entry.bind("<Return>", self._on_separator)
        self.entry.bind("<KeyRelease>", self._on_keyrelease)
        self.entry.focus_set()

        ttk.Button(bottom, text="Cancel", command=self._cancel).pack(anchor="e")

        # Center on parent
        self.win.update_idletasks()
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            ww = self.win.winfo_width()
            wh = self.win.winfo_height()
            self.win.geometry(f"+{px + (pw - ww) // 2}+{py + (ph - wh) // 2}")
        except Exception:
            pass

    def _render_words(self) -> None:
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        for i, word in enumerate(self.words):
            tag = "done" if i < self.idx else ("current" if i == self.idx else "pending")
            self.text.insert(tk.END, word, tag)
            self.text.insert(tk.END, " ")
        self.text.config(state=tk.DISABLED)
        # Scroll to keep current word in view
        try:
            self.text.see(f"1.0 + {sum(len(w) + 1 for w in self.words[:self.idx])} chars")
        except Exception:
            pass

    def _progress_text(self) -> str:
        return f"{self.idx} / {len(self.words)}"

    def _flash_red(self) -> None:
        orig_bg = self.entry.cget("background")
        self.entry.config(background="#ffb3b3")
        self.entry.after(160, lambda: self.entry.config(background=orig_bg))

    def _on_keyrelease(self, event):
        # Space/Return are handled by _on_separator. Backspace shouldn't trigger
        # a typo since the user is correcting; let them shorten the entry freely.
        if event.keysym in ("space", "Return", "BackSpace", "Delete", "Left", "Right",
                            "Home", "End", "Tab", "Shift_L", "Shift_R", "Caps_Lock"):
            return
        if self.idx >= len(self.words):
            return
        typed = self.entry.get()
        if not typed:
            return
        target = self.words[self.idx].lower()
        if not target.startswith(typed.lower()):
            self.entry.delete(0, tk.END)
            self._flash_red()

    def _on_separator(self, event):
        typed = self.entry.get().strip()
        if not typed:
            return "break"
        target = self.words[self.idx]
        if typed.lower() == target.lower():
            self.idx += 1
            self.entry.delete(0, tk.END)
            self._render_words()
            self.progress_var.set(self._progress_text())
            if self.idx >= len(self.words):
                self._complete()
        else:
            # User pressed space too early (entry is a valid prefix but not full word).
            self._flash_red()
            self.entry.delete(0, tk.END)
        return "break"

    def _complete(self) -> None:
        if self._completed:
            return
        self._completed = True
        try:
            self.on_complete()
        finally:
            self.win.destroy()

    def _cancel(self) -> None:
        if not self._completed:
            self.win.destroy()


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------

def _summarize_blocked(config: dict) -> str:
    apps = config.get("blockedApps", [])
    if not apps:
        return "(no apps configured)"
    names: list[str] = []
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


def _format_remaining(seconds: float) -> str:
    if seconds <= 0:
        return "0:00"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def main() -> None:
    load_or_create_config()
    wordlist, wordlist_source = load_wordlist()

    killer = KillerThread()
    killer.start()
    started_at = time.monotonic()

    root = tk.Tk()
    root.title("App Blocker")
    root.geometry("640x540")

    def on_close() -> None:
        killer.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # Banner
    banner_frame = tk.Frame(root, bg="#888")
    banner_frame.pack(fill=tk.X)
    banner_label = tk.Label(
        banner_frame, text="", fg="white", bg="#888",
        font=("TkDefaultFont", 11, "bold"), anchor="w",
    )
    banner_label.pack(fill=tk.X, padx=12, pady=10)

    # Body
    body = ttk.Frame(root, padding=12)
    body.pack(fill=tk.BOTH, expand=True)

    # Break controls
    break_row = ttk.Frame(body)
    break_row.pack(fill=tk.X, pady=(0, 8))
    break_btn = ttk.Button(break_row, text="Take allowance break")
    break_btn.pack(side=tk.LEFT)
    break_status_var = tk.StringVar(value="")
    ttk.Label(break_row, textvariable=break_status_var, foreground="#666").pack(
        side=tk.LEFT, padx=12
    )

    def open_challenge() -> None:
        ok, _reason = killer.can_take_break()
        if not ok:
            return
        word_count = int(killer._settings().get("challengeWordCount", 50))
        word_count = max(1, min(word_count, len(wordlist)))
        words = random.sample(wordlist, word_count)
        ChallengeModal(root, words, on_complete=killer.start_break)

    break_btn.config(command=open_challenge)

    ttk.Separator(body, orient="horizontal").pack(fill=tk.X, pady=4)

    # Config / schedule summary
    config_path_var = tk.StringVar(value=f"Config: {config_path()}")
    ttk.Label(body, textvariable=config_path_var, foreground="#666",
              font=("TkFixedFont", 10)).pack(anchor="w", pady=(4, 0))
    ttk.Label(body, text="(Edit that file to customize. Changes apply within ~1 second.)",
              foreground="#888").pack(anchor="w")

    today_var = tk.StringVar(value="")
    ttk.Label(body, text="Today's schedule:").pack(anchor="w", pady=(8, 0))
    ttk.Label(body, textvariable=today_var, foreground="#222",
              font=("TkFixedFont", 11)).pack(anchor="w")

    blocked_var = tk.StringVar(value="")
    ttk.Label(body, text="Blocked apps:").pack(anchor="w", pady=(8, 0))
    ttk.Label(body, textvariable=blocked_var, foreground="#222",
              font=("TkFixedFont", 11), wraplength=600, justify="left").pack(anchor="w")

    ttk.Separator(body, orient="horizontal").pack(fill=tk.X, pady=10)

    status_var = tk.StringVar(value="Killer thread starting…")
    ttk.Label(body, textvariable=status_var, font=("TkDefaultFont", 11)).pack(anchor="w")

    last_var = tk.StringVar(value="")
    ttk.Label(body, textvariable=last_var, foreground="#0a7",
              wraplength=600, justify="left").pack(anchor="w", pady=(4, 0))

    error_var = tk.StringVar(value="")
    ttk.Label(body, textvariable=error_var, foreground="#b00020",
              wraplength=600, justify="left").pack(anchor="w", pady=(4, 0))

    info_var = tk.StringVar(value=(
        f"Python {sys.version.split()[0]} on {platform.system()} {platform.release()}\n"
        f"Wordlist: {len(wordlist)} words ({wordlist_source})"
    ))
    ttk.Label(body, textvariable=info_var, foreground="#888").pack(anchor="w", pady=(12, 0))

    def reset_state() -> None:
        if not messagebox.askyesno(
            "Reset break / cooldown",
            "Clear any active break and cooldown? "
            "(Soft-mode bypass — for dev iteration.)",
            parent=root,
        ):
            return
        killer.reset_break_state()

    ttk.Button(body, text="Reset break/cooldown", command=reset_state).pack(
        anchor="e", pady=(8, 0)
    )

    def refresh() -> None:
        snap = killer.snapshot()
        cfg = snap["config"]
        window = snap["active_window"]
        now = datetime.now()

        # Banner state
        ends_at = killer.break_ends_at()
        if ends_at and datetime.now() < ends_at:
            remaining = (ends_at - datetime.now()).total_seconds()
            color = "#0a7a3a"
            text = f"  Break active — {_format_remaining(remaining)} remaining"
        elif window:
            color = "#b00020"
            text = (
                f"  Blocking active until {window.get('end','?')}"
                f"  ({window.get('start','?')}–{window.get('end','?')})"
            )
        else:
            color = "#888"
            text = "  No active block"
        banner_frame.config(bg=color)
        banner_label.config(bg=color, text=text)

        # Break button state
        ok, reason = killer.can_take_break()
        if ok:
            break_btn.state(["!disabled"])
            break_status_var.set("Ready — completing the challenge starts a break.")
        else:
            break_btn.state(["disabled"])
            break_status_var.set(reason)

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
