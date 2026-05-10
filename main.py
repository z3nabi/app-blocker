"""App Blocker — Outlook-calendar-driven blocker with allowance-break challenge.

Config:    ~/.app-blocker/config.json   (user-editable; in-app editor too)
State:     ~/.app-blocker/state.json    (managed by app — current break, last
                                         break end for cooldown)
Wordlist:  words.txt next to this file (or embedded fallback)

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
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk
import outlook_calendar
import tray


TICK_INTERVAL = 1.0
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_CONFIG: dict = {
    "_README": (
        "Edit this file to customize. Saved changes are picked up within ~1 second. "
        "Blocking is driven by your Outlook calendar: events tagged with the Outlook "
        "Category specified in calendar.deepWorkCategory (default: 'Deep Work') block "
        "for the duration of the event. No event tagged → no block. "
        "Add names to calendar.additionalCalendars to also scan secondary Outlook "
        "calendars (e.g. ['Work Blocks'])."
    ),
    "blockedApps": [
        {
            "id": "demo-1",
            "displayName": "Demo: Notepad / Calculator",
            "matchers": {"names": ["Notepad", "Notepad.exe", "Calculator"]},
        }
    ],
    "calendar": {
        "deepWorkCategory": "Deep Work",
        "syncIntervalSeconds": 60,
        # Names of secondary Outlook calendars to also scan (in addition to the
        # default). Use the exact display name as it appears in Outlook's
        # folder pane, e.g. ["Work Blocks"]. Missing names are skipped silently.
        "additionalCalendars": [],
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
    "editUnlockUntil": None,
    "manualFocus": None,
}

EDIT_UNLOCK_MINUTES = 5


# ---------------------------------------------------------------------------
# Visual style — Stillwater palette + typography (Direction A · Quiet)
# ---------------------------------------------------------------------------

PAPER = "#FAF7F2"
PAPER_ALT = "#F2EEE6"
WHITE = "#FFFFFF"
INK = "#1F1D1A"
INK2 = "#5C5650"
INK3 = "#8E8780"
LINE = "#E5DFD4"
ACCENT = "#A8553A"
ACCENT_SOFT = "#EAD7CB"
OK_GREEN = "#5E7C45"
WARN = "#A8443A"

_FONT_CACHE: dict[str, str] = {
    "serif": "TkDefaultFont",
    "sans": "TkDefaultFont",
    "mono": "TkFixedFont",
}


def _pick_family(candidates: list[str], available: set[str]) -> str:
    for c in candidates:
        if c in available:
            return c
    return candidates[-1]


def init_fonts(root: tk.Tk) -> None:
    import tkinter.font as tkfont
    avail = set(tkfont.families(root))
    _FONT_CACHE["serif"] = _pick_family(
        ["Source Serif 4", "Source Serif Pro", "Iowan Old Style",
         "Cambria", "Georgia", "Times New Roman"], avail)
    _FONT_CACHE["sans"] = _pick_family(
        ["Inter", "Inter UI", "Segoe UI", "Helvetica Neue",
         "Helvetica", "Arial"], avail)
    _FONT_CACHE["mono"] = _pick_family(
        ["JetBrains Mono", "Cascadia Mono", "Cascadia Code",
         "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"], avail)


def F(role: str, size: int, weight: str = "normal", slant: str = "roman") -> tuple:
    return (_FONT_CACHE.get(role, "TkDefaultFont"), size, weight, slant)


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


def save_config(config: dict) -> None:
    """Atomic write: tempfile + rename."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, indent=2))
    tmp.replace(path)


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


def _pick_latest_window(a: dict | None, b: dict | None) -> dict | None:
    """Choose the window that ends later. Used to merge calendar + manual focus."""
    if a is None:
        return b
    if b is None:
        return a
    a_end = _parse_iso(a.get("end"))
    b_end = _parse_iso(b.get("end"))
    if a_end is None:
        return b
    if b_end is None:
        return a
    return a if a_end >= b_end else b


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
            self._state = {
                "currentBreak": None,
                "lastBreakEndedAt": None,
                "editUnlockUntil": None,
                "manualFocus": None,
            }
            save_state(self._state)

    # -- manual focus session --

    def manual_focus_window(self) -> dict | None:
        """Return the active manual focus session as a window dict, or None.

        Lazily clears expired sessions from state. The returned shape matches
        outlook_calendar.current_deep_work_event so the same downstream code
        treats it as a blocking window.
        """
        with self._lock:
            mf = self._state.get("manualFocus")
            if not mf:
                return None
            ends_at = _parse_iso(mf.get("endsAt"))
            started_at = _parse_iso(mf.get("startedAt"))
            if ends_at is None or datetime.now() >= ends_at:
                self._state["manualFocus"] = None
                save_state(self._state)
                return None
            return {
                "start": started_at.isoformat() if started_at else mf.get("startedAt"),
                "end": ends_at.isoformat(),
                "subject": "Focus session",
                "source": "manual",
            }

    def start_manual_focus(self, minutes: float) -> None:
        with self._lock:
            now = datetime.now()
            ends = now + timedelta(minutes=float(minutes))
            self._state["manualFocus"] = {
                "startedAt": now.isoformat(),
                "endsAt": ends.isoformat(),
                "minutes": float(minutes),
            }
            save_state(self._state)

    # -- edit lock (Phase 7) --

    def is_edit_locked(self) -> bool:
        """True if config edits should be gated by a word challenge.

        Edits are locked when a calendar event is active, and *neither*
        an allowance break nor an edit-unlock grace window is in effect.
        (A break already cost a challenge — let it cover edits too.)
        """
        if self._active_window is None:
            return False
        if self.is_break_active():
            return False
        return self.edit_unlock_remaining_seconds() <= 0

    def edit_unlock_remaining_seconds(self) -> float:
        edit_until = _parse_iso(self._state.get("editUnlockUntil"))
        if edit_until is None:
            return 0.0
        return max(0.0, (edit_until - datetime.now()).total_seconds())

    def start_edit_unlock(self, duration_minutes: float = EDIT_UNLOCK_MINUTES) -> None:
        with self._lock:
            ends = datetime.now() + timedelta(minutes=duration_minutes)
            self._state["editUnlockUntil"] = ends.isoformat()
            save_state(self._state)

    # -- main loop --

    def run(self) -> None:
        while not self._stop.is_set():
            tick_start = time.monotonic()
            killed: list[str] = []
            method = self._method
            self._reload_config()

            now = datetime.now()
            calendar_window = outlook_calendar.current_deep_work_event(now)
            manual_window = self.manual_focus_window()
            window = _pick_latest_window(calendar_window, manual_window)

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
        self.win.geometry("840x540")
        self.win.configure(bg=WHITE)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)

        outer = tk.Frame(self.win, bg=WHITE)
        outer.pack(fill=tk.BOTH, expand=True, padx=44, pady=32)

        tk.Label(outer, text=f"ALLOWANCE BREAK · {len(words)} WORDS",
                 bg=WHITE, fg=INK3, font=F("sans", 9, "bold"), anchor="w"
                 ).pack(anchor="w")
        tk.Label(outer, text=f"Type these {len(words)} words.",
                 bg=WHITE, fg=INK, font=F("serif", 26), anchor="w"
                 ).pack(anchor="w", pady=(4, 6))
        tk.Label(outer,
                 text="Space or Enter advances. Typos clear the current word and you start it over.",
                 bg=WHITE, fg=INK2, font=F("sans", 11),
                 wraplength=720, justify="left", anchor="w"
                 ).pack(anchor="w", pady=(0, 18))

        prog_row = tk.Frame(outer, bg=WHITE)
        prog_row.pack(fill=tk.X, pady=(0, 14))
        self.prog_canvas = tk.Canvas(prog_row, height=4, bg=LINE,
                                     highlightthickness=0)
        self.prog_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True,
                              padx=(0, 14))
        self.progress_var = tk.StringVar(value=self._progress_text())
        tk.Label(prog_row, textvariable=self.progress_var, bg=WHITE, fg=INK2,
                 font=F("mono", 11)).pack(side=tk.RIGHT)

        # Bottom-anchored widgets first so they can never be squeezed off the
        # screen by an over-tall middle widget. Pack order matters with
        # side=BOTTOM: the first call gets the very bottom slot.
        foot = tk.Frame(outer, bg=WHITE)
        foot.pack(side=tk.BOTTOM, fill=tk.X, pady=(14, 0))

        input_row = tk.Frame(outer, bg=WHITE,
                             highlightthickness=1, highlightbackground=INK)
        input_row.pack(side=tk.BOTTOM, fill=tk.X)

        word_card = tk.Frame(outer, bg=PAPER,
                             highlightthickness=1, highlightbackground=LINE)
        word_card.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 14))
        # height in lines — without this tk.Text defaults to 24, requesting
        # ~528px of vertical space which overflows the 540px modal and clips
        # the input row + Cancel button below it (Entry winds up unmapped,
        # so focus_force on it silently no-ops).
        self.text = tk.Text(
            word_card, wrap=tk.WORD,
            font=(_FONT_CACHE["serif"], 16),
            bg=PAPER, fg=INK2, padx=28, pady=24,
            relief="flat", borderwidth=0, highlightthickness=0,
            spacing1=4, spacing3=4,
            height=8,
        )
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.tag_configure("done", foreground=INK3)
        self.text.tag_configure(
            "current", foreground=INK, background=WHITE,
            font=(_FONT_CACHE["serif"], 16, "bold"),
        )
        self.text.tag_configure("pending", foreground=INK2)
        self._render_words()
        self.text.config(state=tk.DISABLED)
        input_pad = tk.Frame(input_row, bg=WHITE)
        input_pad.pack(fill=tk.X, padx=18, pady=14)
        tk.Label(input_pad, text="WORD", bg=WHITE, fg=INK3,
                 font=F("mono", 9, "bold")).pack(side=tk.LEFT)
        self.idx_label_var = tk.StringVar(value="01")
        tk.Label(input_pad, textvariable=self.idx_label_var,
                 bg=ACCENT, fg=WHITE, font=F("mono", 10, "bold"),
                 padx=8, pady=2).pack(side=tk.LEFT, padx=(8, 14))
        self.entry = tk.Entry(input_pad, font=F("mono", 16),
                              bg=WHITE, fg=INK,
                              relief="flat", borderwidth=0,
                              highlightthickness=0,
                              insertbackground=ACCENT)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<space>", self._on_separator)
        self.entry.bind("<Return>", self._on_separator)
        self.entry.bind("<KeyRelease>", self._on_keyrelease)
        self.entry.focus_set()

        tk.Button(
            foot, text="Cancel", command=self._cancel,
            bg=WHITE, fg=INK2, activebackground=PAPER_ALT,
            activeforeground=INK, font=F("sans", 10),
            relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=LINE,
            padx=14, pady=6, cursor="hand2",
        ).pack(side=tk.RIGHT)

        self._update_idx_label()
        self.prog_canvas.bind("<Configure>", lambda e: self._draw_progress())
        self._draw_progress()

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

    def _draw_progress(self) -> None:
        self.prog_canvas.delete("all")
        w = self.prog_canvas.winfo_width()
        if w < 4 or not self.words:
            return
        frac = self.idx / len(self.words)
        if frac > 0:
            self.prog_canvas.create_rectangle(
                0, 0, int(w * frac), 4, fill=ACCENT, outline=""
            )

    def _update_idx_label(self) -> None:
        n = len(self.words)
        cur = min(self.idx + 1, n)
        self.idx_label_var.set(f"{cur:02d} / {n}")

    def _render_words(self) -> None:
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        for i, word in enumerate(self.words):
            tag = "done" if i < self.idx else ("current" if i == self.idx else "pending")
            self.text.insert(tk.END, word, tag)
            self.text.insert(tk.END, " ")
        self.text.config(state=tk.DISABLED)
        try:
            self.text.see(f"1.0 + {sum(len(w) + 1 for w in self.words[:self.idx])} chars")
        except Exception:
            pass

    def _progress_text(self) -> str:
        return f"{self.idx:02d} / {len(self.words):02d}"

    def _flash_red(self) -> None:
        self.entry.config(foreground=WARN)
        self.entry.after(160, lambda: self.entry.config(foreground=INK))

    def _on_keyrelease(self, event):
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
            self._update_idx_label()
            self._draw_progress()
            if self.idx >= len(self.words):
                self._complete()
        else:
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
# Process picker (modal)
# ---------------------------------------------------------------------------

class AppPicker:
    def __init__(self, parent: tk.Tk, on_pick) -> None:
        self.on_pick = on_pick
        self.win = tk.Toplevel(parent)
        self.win.title("Add app to block list")
        self.win.geometry("460x520")
        self.win.transient(parent)
        self.win.grab_set()

        header = ttk.Frame(self.win, padding=(12, 12, 12, 4))
        header.pack(fill=tk.X)
        ttk.Label(header, text="Pick a running process to block:",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(header,
                  text="Tip: open the app you want to block first, then click Refresh.",
                  foreground="#666").pack(anchor="w", pady=(2, 0))

        search_row = ttk.Frame(self.win, padding=(12, 4, 12, 4))
        search_row.pack(fill=tk.X)
        ttk.Label(search_row, text="Filter:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._refilter())
        ttk.Entry(search_row, textvariable=self.search_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0)
        )

        list_frame = ttk.Frame(self.win, padding=(12, 4, 12, 8))
        list_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_frame)
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, activestyle="none")
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-Button-1>", lambda e: self._on_add())
        self.listbox.bind("<Return>", lambda e: self._on_add())

        btns = ttk.Frame(self.win, padding=(12, 0, 12, 12))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Refresh", command=self._refresh).pack(side=tk.LEFT)
        ttk.Button(btns, text="Cancel", command=self.win.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Add", command=self._on_add).pack(side=tk.RIGHT, padx=4)

        self._all: list[str] = []
        self._refresh()

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

    def _refresh(self) -> None:
        try:
            procs, _ = list_processes()
        except Exception:
            procs = []
        self._all = sorted({n for _, n in procs}, key=str.lower)
        self._refilter()

    def _refilter(self) -> None:
        q = self.search_var.get().lower().strip()
        self.listbox.delete(0, tk.END)
        for name in self._all:
            if q in name.lower():
                self.listbox.insert(tk.END, name)

    def _on_add(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        try:
            self.on_pick(name)
        finally:
            self.win.destroy()


# ---------------------------------------------------------------------------
# Launch at login (Phase 8)
# ---------------------------------------------------------------------------

LAUNCH_LABEL = "com.simon.appblocker"


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"


def _windows_startup_path() -> Path:
    base = Path(os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    ))
    return base / "AppBlocker.bat"


def is_launch_at_login_installed() -> bool:
    if sys.platform == "darwin":
        return _macos_plist_path().exists()
    if sys.platform == "win32":
        return _windows_startup_path().exists()
    return False


def install_launch_at_login() -> tuple[bool, str]:
    main_py = Path(__file__).resolve()
    if sys.platform == "darwin":
        p = _macos_plist_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCH_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{main_py}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
'''
        p.write_text(plist)
        try:
            subprocess.run(["launchctl", "load", str(p)], check=False, capture_output=True)
        except Exception:
            pass
        return True, str(p)
    if sys.platform == "win32":
        # Use pythonw.exe so no console window flashes at login.
        pythonw = sys.executable
        if pythonw.lower().endswith("python.exe"):
            cand = Path(pythonw).with_name("pythonw.exe")
            if cand.exists():
                pythonw = str(cand)
        bat = f'@echo off\r\nstart "" "{pythonw}" "{main_py}"\r\n'
        p = _windows_startup_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(bat)
        return True, str(p)
    return False, "Launch-at-login not supported on this platform."


def uninstall_launch_at_login() -> tuple[bool, str]:
    if sys.platform == "darwin":
        p = _macos_plist_path()
        if p.exists():
            try:
                subprocess.run(["launchctl", "unload", str(p)], check=False, capture_output=True)
            except Exception:
                pass
            try:
                p.unlink()
            except OSError as e:
                return False, str(e)
        return True, ""
    if sys.platform == "win32":
        p = _windows_startup_path()
        if p.exists():
            try:
                p.unlink()
            except OSError as e:
                return False, str(e)
        return True, ""
    return False, "Launch-at-login not supported on this platform."



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


def _summarize_calendar_today(now: datetime) -> str:
    """Hero-meta line for the Today page: describes the next/current Deep Work block."""
    current = outlook_calendar.current_deep_work_event(now)
    if current is not None:
        try:
            end = datetime.fromisoformat(current["end"])
            return f"Deep work · ends {end.strftime('%H:%M')}"
        except (KeyError, ValueError):
            return "Deep work · in progress"
    # Look ahead for today's next Deep Work block.
    cache = outlook_calendar._snapshot_cache()
    upcoming = []
    for ev in cache.get("events", []):
        try:
            # Strip tzinfo: pywintypes emits tz-aware ISO strings, but `now` is
            # naive (datetime.now()). Same defense as outlook_calendar._event_covers.
            start = datetime.fromisoformat(ev["start"]).replace(tzinfo=None)
            if start > now and start.date() == now.date():
                upcoming.append((start, ev))
        except (KeyError, ValueError):
            continue
    upcoming.sort(key=lambda pair: pair[0])
    if upcoming:
        return f"Next deep work: {upcoming[0][0].strftime('%H:%M')}"
    return "No deep work blocks today"


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
    root.title("Stillwater · App Blocker")
    root.geometry("1100x720")
    root.minsize(940, 600)
    root.configure(bg=PAPER)
    init_fonts(root)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Treeview",
        background=WHITE, foreground=INK, fieldbackground=WHITE,
        bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
        font=F("sans", 10), rowheight=26, borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        background=PAPER, foreground=INK2,
        font=F("sans", 9, "bold"), bordercolor=LINE, relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", PAPER_ALT)],
        foreground=[("selected", INK)],
    )
    style.configure(
        "Vertical.TScrollbar",
        background=PAPER, troughcolor=PAPER_ALT,
        bordercolor=PAPER, arrowcolor=INK2,
        lightcolor=PAPER, darkcolor=PAPER,
    )

    tray_icon: tray.TrayIcon | None = None

    def _restore_window() -> None:
        try:
            root.deiconify()
        except tk.TclError:
            return
        root.state("normal")
        root.lift()
        root.focus_force()

    def _quit_app() -> None:
        if tray_icon is not None:
            tray_icon.stop()
        killer.stop()
        try:
            root.destroy()
        except tk.TclError:
            pass

    if tray.HAVE_WIN32 and sys.platform == "win32":
        try:
            icon_path = Path(__file__).resolve().parent / "assets" / "stillwater.ico"
            tray_icon = tray.TrayIcon(
                title="Stillwater · App Blocker",
                on_show=lambda: root.after(0, _restore_window),
                on_quit=lambda: root.after(0, _quit_app),
                icon_path=icon_path if icon_path.is_file() else None,
            )
            tray_icon.start()
        except Exception:
            tray_icon = None

    def on_close() -> None:
        if tray_icon is not None:
            root.withdraw()
        else:
            _quit_app()

    def on_unmap(event) -> None:
        if event.widget is root and tray_icon is not None:
            try:
                if root.state() == "iconic":
                    root.withdraw()
            except tk.TclError:
                pass

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.bind("<Unmap>", on_unmap)

    def make_button(parent, text, command) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command,
            bg=INK, fg=WHITE, activebackground=INK2, activeforeground=WHITE,
            disabledforeground=INK3,
            font=F("sans", 10), padx=18, pady=8,
            relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=INK,
            cursor="hand2",
        )

    def set_button_enabled(btn: tk.Button, enabled: bool) -> None:
        """Toggle visual + interactive state. tk.Button's default disabled
        rendering only dims the foreground; we also flip bg/border/cursor
        so the difference is unmistakable on this palette."""
        if enabled:
            btn.config(state=tk.NORMAL, bg=INK, fg=WHITE,
                       highlightbackground=INK, cursor="hand2")
        else:
            btn.config(state=tk.DISABLED, bg=PAPER, fg=INK3,
                       highlightbackground=LINE, cursor="arrow")

    def _challenge_word_count() -> int:
        n = int(killer._settings().get("challengeWordCount", 50))
        return max(1, min(n, len(wordlist)))

    def open_challenge() -> None:
        ok, _reason = killer.can_take_break()
        if not ok:
            return
        words = random.sample(wordlist, _challenge_word_count())
        ChallengeModal(root, words, on_complete=killer.start_break)

    def open_edit_unlock_challenge() -> None:
        if not killer.is_edit_locked():
            return
        words = random.sample(wordlist, _challenge_word_count())
        ChallengeModal(root, words, on_complete=killer.start_edit_unlock)

    # ---- Shell: sidebar | content ----
    shell = tk.Frame(root, bg=PAPER)
    shell.pack(fill=tk.BOTH, expand=True)

    sidebar = tk.Frame(shell, bg=PAPER, width=216)
    sidebar.pack(side=tk.LEFT, fill=tk.Y)
    sidebar.pack_propagate(False)
    tk.Frame(shell, bg=LINE, width=1).pack(side=tk.LEFT, fill=tk.Y)
    content = tk.Frame(shell, bg=WHITE)
    content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # ---- Sidebar: brand, nav, active-block strip ----
    brand = tk.Frame(sidebar, bg=PAPER)
    brand.pack(fill=tk.X, padx=22, pady=(24, 22))
    tk.Label(
        brand, text="Stillwater", bg=PAPER, fg=INK,
        font=(_FONT_CACHE["serif"], 19, "normal", "italic"),
    ).pack(anchor="w")

    nav_holder = tk.Frame(sidebar, bg=PAPER)
    nav_holder.pack(fill=tk.X, padx=12)

    nav_items = [
        ("today", "Today"),
        ("calendar", "Calendar"),
        ("blocks", "Block lists"),
        ("settings", "Settings"),
    ]
    nav_widgets: dict[str, dict] = {}
    current_page = tk.StringVar(value="today")
    pages: dict[str, tk.Frame] = {}

    def set_page(key: str) -> None:
        current_page.set(key)
        update_nav_visual()
        for k, frame in pages.items():
            if k == key:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()

    def update_nav_visual() -> None:
        for k, w in nav_widgets.items():
            active = (k == current_page.get())
            bg = PAPER_ALT if active else PAPER
            fg = INK if active else INK2
            font = F("sans", 11, "bold" if active else "normal")
            w["label"].config(bg=bg, fg=fg, font=font)

    for key, label in nav_items:
        # Single-widget row: one Label that fills the whole sidebar width.
        # macOS Tk hit-testing across nested frames + multiple click
        # targets is unreliable; collapsing to one widget per row makes
        # the click target unambiguous.
        lbl = tk.Label(
            nav_holder, text=label, bg=PAPER, fg=INK2,
            font=F("sans", 11), padx=12, pady=8, anchor="w",
            cursor="hand2",
        )
        lbl.pack(fill=tk.X)
        # Bind both press and release — any reachable click cycle fires.
        click = (lambda k=key: lambda e: set_page(k))()
        lbl.bind("<Button-1>", click)
        lbl.bind("<ButtonRelease-1>", click)
        nav_widgets[key] = {"label": lbl, "base_text": label}

    sb_strip = tk.Frame(sidebar, bg=PAPER)
    sb_strip.pack(side=tk.BOTTOM, fill=tk.X, padx=22, pady=(0, 22))
    tk.Frame(sb_strip, bg=LINE, height=1).pack(fill=tk.X, pady=(0, 14))
    tk.Label(
        sb_strip, text="ACTIVE BLOCK", bg=PAPER, fg=INK3,
        font=F("sans", 9, "bold"), anchor="w",
    ).pack(fill=tk.X)
    sb_label_var = tk.StringVar(value="None")
    tk.Label(
        sb_strip, textvariable=sb_label_var, bg=PAPER, fg=INK,
        font=F("serif", 14), anchor="w",
    ).pack(fill=tk.X, pady=(4, 0))
    sb_sub_var = tk.StringVar(value="")
    tk.Label(
        sb_strip, textvariable=sb_sub_var, bg=PAPER, fg=INK2,
        font=F("mono", 10), anchor="w",
    ).pack(fill=tk.X, pady=(2, 0))

    # =========================================================================
    # Today page
    # =========================================================================
    today_page = tk.Frame(content, bg=WHITE)
    pages["today"] = today_page
    # Scrollable Today: Canvas + Scrollbar wrap a padded inner frame so
    # content overflowing the window height can be scrolled.
    _today_canvas = tk.Canvas(today_page, bg=WHITE, highlightthickness=0)
    _today_vsb = ttk.Scrollbar(today_page, orient="vertical", command=_today_canvas.yview)
    _today_canvas.configure(yscrollcommand=_today_vsb.set)
    _today_vsb.pack(side=tk.RIGHT, fill=tk.Y)
    _today_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    _today_padframe = tk.Frame(_today_canvas, bg=WHITE)
    _today_padframe_id = _today_canvas.create_window((0, 0), window=_today_padframe, anchor="nw")
    today_inner = tk.Frame(_today_padframe, bg=WHITE)
    today_inner.pack(fill=tk.BOTH, expand=True, padx=48, pady=36)

    def _on_today_padframe_configure(_e):
        _today_canvas.configure(scrollregion=_today_canvas.bbox("all"))

    def _on_today_canvas_configure(e):
        # Track canvas width so the padded inner frame fills the viewport.
        _today_canvas.itemconfigure(_today_padframe_id, width=e.width)

    _today_padframe.bind("<Configure>", _on_today_padframe_configure)
    _today_canvas.bind("<Configure>", _on_today_canvas_configure)

    def _on_today_mousewheel(e):
        if current_page.get() != "today":
            return
        # macOS sends small deltas; Windows sends multiples of 120.
        if sys.platform == "darwin":
            _today_canvas.yview_scroll(-1 * e.delta, "units")
        else:
            _today_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    root.bind_all("<MouseWheel>", _on_today_mousewheel, add="+")
    root.bind_all(
        "<Button-4>",
        lambda e: _today_canvas.yview_scroll(-1, "units") if current_page.get() == "today" else None,
        add="+",
    )
    root.bind_all(
        "<Button-5>",
        lambda e: _today_canvas.yview_scroll(1, "units") if current_page.get() == "today" else None,
        add="+",
    )

    today_date_var = tk.StringVar(value="")
    tk.Label(
        today_inner, textvariable=today_date_var, bg=WHITE, fg=INK3,
        font=F("sans", 9, "bold"), anchor="w",
    ).pack(anchor="w")
    tk.Label(
        today_inner, text="Today.", bg=WHITE, fg=INK,
        font=F("serif", 30), anchor="w",
    ).pack(anchor="w", pady=(4, 22))

    hero = tk.Frame(
        today_inner, bg=PAPER,
        highlightthickness=1, highlightbackground=LINE,
    )
    hero.pack(fill=tk.X, pady=(0, 22))
    hero_l = tk.Frame(hero, bg=PAPER)
    hero_l.pack(side=tk.LEFT, padx=28, pady=22, fill=tk.X, expand=True)
    pill_row = tk.Frame(hero_l, bg=PAPER)
    pill_row.pack(anchor="w")
    pill_dot = tk.Frame(pill_row, bg=ACCENT, width=6, height=6)
    pill_dot.pack(side=tk.LEFT, pady=(3, 0))
    pill_var = tk.StringVar(value="")
    pill_label = tk.Label(
        pill_row, textvariable=pill_var, bg=PAPER, fg=ACCENT,
        font=F("sans", 9, "bold"),
    )
    pill_label.pack(side=tk.LEFT, padx=8)
    hero_session_var = tk.StringVar(value="No active block")
    tk.Label(
        hero_l, textvariable=hero_session_var, bg=PAPER, fg=INK,
        font=F("serif", 24), anchor="w",
    ).pack(anchor="w", pady=(10, 4))
    hero_meta_var = tk.StringVar(value="")
    tk.Label(
        hero_l, textvariable=hero_meta_var, bg=PAPER, fg=INK2,
        font=F("sans", 11), anchor="w",
    ).pack(anchor="w")
    hero_r = tk.Frame(hero, bg=PAPER)
    hero_r.pack(side=tk.RIGHT, padx=32, pady=22)
    hero_time_var = tk.StringVar(value="—")
    tk.Label(
        hero_r, textvariable=hero_time_var, bg=PAPER, fg=INK,
        font=F("serif", 44), anchor="e",
    ).pack(anchor="e")
    tk.Label(
        hero_r, text="REMAINING", bg=PAPER, fg=INK3,
        font=F("sans", 9, "bold"),
    ).pack(anchor="e", pady=(2, 0))

    actions_row = tk.Frame(today_inner, bg=WHITE)
    actions_row.pack(fill=tk.X, pady=(0, 22))
    # Inner holder packed without fill/anchor → x-centered in actions_row.
    actions_inner = tk.Frame(actions_row, bg=WHITE)
    actions_inner.pack()

    def start_focus(minutes: int) -> None:
        if killer.manual_focus_window() is not None:
            return
        if outlook_calendar.current_deep_work_event(datetime.now()) is not None:
            return
        if killer.is_break_active():
            return
        if not messagebox.askyesno(
            "Start focus session",
            f"Start a {minutes}-minute focus session now?\n\n"
            "Blocked apps will be killed for the duration. "
            "An allowance break will require the usual word challenge.",
            parent=root,
        ):
            return
        killer.start_manual_focus(minutes)

    focus_30_btn = make_button(
        actions_inner, "Focus 30 min", lambda: start_focus(30),
    )
    focus_30_btn.pack(side=tk.LEFT)
    focus_60_btn = make_button(
        actions_inner, "Focus 60 min", lambda: start_focus(60),
    )
    # Tight pair, then a wider gap before the conceptually-distinct allowance.
    focus_60_btn.pack(side=tk.LEFT, padx=(6, 28))
    break_btn = make_button(
        actions_inner, "Allowance break", open_challenge,
    )
    break_btn.pack(side=tk.LEFT)

    allowance_caption_var = tk.StringVar(value="")
    tk.Label(
        actions_row, textvariable=allowance_caption_var, bg=WHITE, fg=INK3,
        font=F("sans", 10),
    ).pack(pady=(8, 0))

    stats_grid = tk.Frame(
        today_inner, bg=LINE,
        highlightthickness=1, highlightbackground=LINE,
    )
    stats_grid.pack(fill=tk.X, pady=(0, 24))
    for i in range(3):
        stats_grid.columnconfigure(i, weight=1, uniform="stat")
    stat_kills_var = tk.StringVar(value="0")
    stat_kills_sub_var = tk.StringVar(value="attempts")
    stat_uptime_var = tk.StringVar(value="—")
    stat_uptime_sub_var = tk.StringVar(value="uptime")
    stat_cooldown_var = tk.StringVar(value="—")
    stat_cooldown_sub_var = tk.StringVar(value="allowance")

    def _stat_cell(col, label, val_var, sub_var):
        c = tk.Frame(stats_grid, bg=WHITE)
        c.grid(
            row=0, column=col, sticky="nsew",
            padx=(0 if col == 0 else 1, 0), pady=0,
        )
        tk.Label(
            c, text=label, bg=WHITE, fg=INK3,
            font=F("sans", 9, "bold"), anchor="w",
        ).pack(anchor="w", padx=22, pady=(20, 6))
        tk.Label(
            c, textvariable=val_var, bg=WHITE, fg=INK,
            font=F("serif", 26), anchor="w",
        ).pack(anchor="w", padx=22)
        tk.Label(
            c, textvariable=sub_var, bg=WHITE, fg=INK2,
            font=F("sans", 10), anchor="w",
        ).pack(anchor="w", padx=22, pady=(2, 20))

    _stat_cell(0, "BLOCKED", stat_kills_var, stat_kills_sub_var)
    _stat_cell(1, "RUNNING", stat_uptime_var, stat_uptime_sub_var)
    _stat_cell(2, "ALLOWANCE", stat_cooldown_var, stat_cooldown_sub_var)

    today_section_h = tk.Frame(today_inner, bg=WHITE)
    today_section_h.pack(fill=tk.X)
    tk.Label(
        today_section_h, text="Recent activity", bg=WHITE, fg=INK,
        font=F("serif", 16), anchor="w",
    ).pack(side=tk.LEFT)

    last_killed_card = tk.Frame(
        today_inner, bg=PAPER,
        highlightthickness=1, highlightbackground=LINE,
    )
    last_killed_card.pack(fill=tk.X, pady=(10, 12))
    last_killed_var = tk.StringVar(value="No kills yet.")
    tk.Label(
        last_killed_card, textvariable=last_killed_var,
        bg=PAPER, fg=INK2, font=F("mono", 10),
        anchor="w", justify="left", wraplength=900,
    ).pack(fill=tk.X, padx=20, pady=14)

    diag_var = tk.StringVar(value="")
    tk.Label(
        today_inner, textvariable=diag_var, bg=WHITE, fg=INK3,
        font=F("mono", 9), anchor="w", justify="left",
    ).pack(anchor="w", pady=(4, 0))
    err_var = tk.StringVar(value="")
    tk.Label(
        today_inner, textvariable=err_var, bg=WHITE, fg=WARN,
        font=F("sans", 10), anchor="w",
    ).pack(anchor="w", pady=(2, 0))

    def reset_state() -> None:
        if not messagebox.askyesno(
            "Reset break / cooldown",
            "Clear any active break and cooldown? "
            "(Dev-only soft-mode bypass.)",
            parent=root,
        ):
            return
        killer.reset_break_state()

    # DEV-ONLY: reset button. Remove before shipping for real use.
    make_button(
        today_inner, "Reset break/cooldown [dev]", reset_state,
    ).pack(anchor="e", pady=(16, 0))

    # =========================================================================
    # Calendar page
    # =========================================================================
    calendar_page = tk.Frame(content, bg=WHITE)
    pages["calendar"] = calendar_page
    cal_inner = tk.Frame(calendar_page, bg=WHITE)
    cal_inner.pack(fill="both", expand=True, padx=24, pady=24)

    tk.Label(
        cal_inner, text="TODAY'S DEEP WORK BLOCKS", bg=WHITE, fg=INK3,
        font=(_FONT_CACHE["sans"], 11, "bold"),
    ).pack(anchor="w", pady=(0, 12))

    cal_list_frame = tk.Frame(cal_inner, bg=WHITE)
    cal_list_frame.pack(fill="x", anchor="w")

    cal_status_var = tk.StringVar(value="")

    def refresh_calendar_page() -> None:
        for child in cal_list_frame.winfo_children():
            child.destroy()
        cache = outlook_calendar._snapshot_cache()
        events = cache.get("events", [])
        if not events:
            tk.Label(
                cal_list_frame, text="No Deep Work events today.", bg=WHITE, fg=INK2,
                font=(_FONT_CACHE["serif"], 14),
            ).pack(anchor="w")
        else:
            # Sort by start time for display.
            sortable = []
            for ev in events:
                try:
                    sortable.append((datetime.fromisoformat(ev["start"]), ev))
                except (KeyError, ValueError):
                    continue
            sortable.sort(key=lambda pair: pair[0])
            for start, ev in sortable:
                try:
                    end = datetime.fromisoformat(ev["end"])
                except (KeyError, ValueError):
                    continue
                line = f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}    {ev.get('subject', '')}"
                tk.Label(cal_list_frame, text=line, bg=WHITE, fg=INK,
                         font=(_FONT_CACHE["serif"], 14)).pack(anchor="w", pady=2)
        # Status line.
        status = outlook_calendar.last_sync_status()
        if status["ok"]:
            cal_status_var.set(f"Last synced at {status['at']}")
        elif status["error"]:
            cal_status_var.set(status["error"])
        else:
            cal_status_var.set("Never synced")

    tk.Frame(cal_inner, bg=LINE, height=1).pack(fill="x", pady=(20, 12))
    tk.Label(cal_inner, textvariable=cal_status_var, bg=WHITE, fg=INK3,
             font=(_FONT_CACHE["sans"], 11)).pack(anchor="w")

    def on_sync_now():
        outlook_calendar.force_refresh()
        # Give the sync thread a brief moment, then refresh the page.
        cal_inner.after(500, refresh_calendar_page)

    tk.Button(cal_inner, text="Sync now", command=on_sync_now,
              bg=PAPER_ALT, fg=INK, relief="flat",
              font=(_FONT_CACHE["sans"], 11)).pack(anchor="w", pady=(12, 0))

    refresh_calendar_page()

    # =========================================================================
    # Block lists page
    # =========================================================================
    blocks_page = tk.Frame(content, bg=WHITE)
    pages["blocks"] = blocks_page
    blocks_inner = tk.Frame(blocks_page, bg=WHITE)
    blocks_inner.pack(fill=tk.BOTH, expand=True, padx=48, pady=36)

    tk.Label(
        blocks_inner, text="BLOCK LISTS", bg=WHITE, fg=INK3,
        font=F("sans", 9, "bold"), anchor="w",
    ).pack(anchor="w")
    tk.Label(
        blocks_inner, text="Process names to silence.",
        bg=WHITE, fg=INK, font=F("serif", 26), anchor="w",
    ).pack(anchor="w", pady=(4, 8))
    tk.Label(
        blocks_inner,
        text="Killed during active Deep Work calendar events. Edit the JSON config for advanced matchers.",
        bg=WHITE, fg=INK2, font=F("sans", 11), anchor="w",
        wraplength=720, justify="left",
    ).pack(anchor="w", pady=(0, 22))

    blocks_lock_banner = tk.Frame(
        blocks_inner, bg=PAPER_ALT,
        highlightthickness=1, highlightbackground=LINE,
    )
    blocks_lock_label = tk.Label(
        blocks_lock_banner, bg=PAPER_ALT, fg=INK,
        text="List frozen during active block.",
        font=F("sans", 11), anchor="w",
    )
    blocks_lock_label.pack(side=tk.LEFT, padx=14, pady=10)
    blocks_unlock_btn = make_button(
        blocks_lock_banner, "Unlock to edit", open_edit_unlock_challenge,
    )
    blocks_unlock_btn.pack(side=tk.RIGHT, padx=10, pady=8)

    blocks_card = tk.Frame(
        blocks_inner, bg=WHITE,
        highlightthickness=1, highlightbackground=LINE,
    )
    blocks_card.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
    apps_scroll = ttk.Scrollbar(blocks_card)
    apps_listbox = tk.Listbox(
        blocks_card, yscrollcommand=apps_scroll.set,
        activestyle="none", relief="flat", borderwidth=0,
        bg=WHITE, fg=INK, font=F("sans", 11),
        highlightthickness=0,
        selectbackground=PAPER_ALT, selectforeground=INK,
    )
    apps_scroll.config(command=apps_listbox.yview)
    apps_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1))
    apps_listbox.pack(
        side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=10,
    )

    displayed_app_ids: list[str] = []

    def refresh_apps_list() -> None:
        snap = killer.snapshot()
        apps = snap["config"].get("blockedApps", [])
        sel = apps_listbox.curselection()
        sel_idx = sel[0] if sel else None
        apps_listbox.delete(0, tk.END)
        displayed_app_ids.clear()
        for app in apps:
            display = app.get("displayName", "(unnamed)")
            names = app.get("matchers", {}).get("names", [])
            apps_listbox.insert(tk.END, f"{display}  —  {', '.join(names)}")
            displayed_app_ids.append(app.get("id", ""))
        if sel_idx is not None and sel_idx < len(apps):
            apps_listbox.selection_set(sel_idx)

    def add_app_via_picker() -> None:
        def on_pick(name: str) -> None:
            snap = killer.snapshot()
            cfg = json.loads(json.dumps(snap["config"]))
            cfg.setdefault("blockedApps", []).append({
                "id": str(uuid.uuid4()),
                "displayName": name,
                "matchers": {"names": [name]},
            })
            save_config(cfg)
        AppPicker(root, on_pick=on_pick)

    def remove_selected_app() -> None:
        sel = apps_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(displayed_app_ids):
            return
        app_id = displayed_app_ids[idx]
        snap = killer.snapshot()
        cfg = json.loads(json.dumps(snap["config"]))
        cfg["blockedApps"] = [
            a for a in cfg.get("blockedApps", []) if a.get("id") != app_id
        ]
        save_config(cfg)

    blocks_btns = tk.Frame(blocks_inner, bg=WHITE)
    blocks_btns.pack(fill=tk.X)
    apps_add_btn = make_button(blocks_btns, "Add…", add_app_via_picker)
    apps_remove_btn = make_button(blocks_btns, "Remove selected", remove_selected_app)
    apps_add_btn.pack(side=tk.LEFT, padx=(0, 8))
    apps_remove_btn.pack(side=tk.LEFT)

    # =========================================================================
    # Settings page
    # =========================================================================
    settings_page = tk.Frame(content, bg=WHITE)
    pages["settings"] = settings_page
    s_inner = tk.Frame(settings_page, bg=WHITE)
    s_inner.pack(fill=tk.BOTH, expand=True, padx=48, pady=36)

    tk.Label(
        s_inner, text="SETTINGS", bg=WHITE, fg=INK3,
        font=F("sans", 9, "bold"), anchor="w",
    ).pack(anchor="w")
    tk.Label(
        s_inner, text="Tuning.", bg=WHITE, fg=INK,
        font=F("serif", 26), anchor="w",
    ).pack(anchor="w", pady=(4, 22))

    s_card = tk.Frame(
        s_inner, bg=PAPER,
        highlightthickness=1, highlightbackground=LINE,
    )
    s_card.pack(fill=tk.X, pady=(0, 14))
    s_grid = tk.Frame(s_card, bg=PAPER)
    s_grid.pack(fill=tk.X, padx=28, pady=22)

    break_var = tk.IntVar(value=10)
    cooldown_var = tk.IntVar(value=30)
    words_var = tk.IntVar(value=50)
    settings_loading = [False]
    spinboxes: list[tk.Spinbox] = []

    def write_settings_from_vars() -> None:
        if settings_loading[0]:
            return
        snap = killer.snapshot()
        cfg = json.loads(json.dumps(snap["config"]))
        try:
            br = max(1, int(break_var.get()))
            cd = max(0, int(cooldown_var.get()))
            wc = max(1, min(int(words_var.get()), len(wordlist)))
        except (TypeError, ValueError, tk.TclError):
            return
        cfg.setdefault("settings", {})
        cfg["settings"]["breakDurationMinutes"] = br
        cfg["settings"]["cooldownMinutes"] = cd
        cfg["settings"]["challengeWordCount"] = wc
        save_config(cfg)

    def load_settings_from_config(cfg: dict) -> None:
        s = cfg.get("settings", {}) or {}
        settings_loading[0] = True
        try:
            break_var.set(int(s.get("breakDurationMinutes", 10)))
            cooldown_var.set(int(s.get("cooldownMinutes", 30)))
            words_var.set(int(s.get("challengeWordCount", 50)))
        except (TypeError, ValueError):
            pass
        finally:
            settings_loading[0] = False

    def add_setting_row(row, label, var, lo, hi, suffix):
        tk.Label(
            s_grid, text=label, bg=PAPER, fg=INK,
            font=F("sans", 11), anchor="w",
        ).grid(row=row, column=0, sticky="w", pady=10)
        sb = tk.Spinbox(
            s_grid, from_=lo, to=hi, textvariable=var, width=6,
            bg=WHITE, fg=INK, font=F("mono", 12),
            relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=LINE,
            buttonbackground=PAPER_ALT,
            command=write_settings_from_vars,
        )
        sb.grid(row=row, column=1, sticky="w", padx=18, pady=10)
        tk.Label(
            s_grid, text=suffix, bg=PAPER, fg=INK2,
            font=F("sans", 10), anchor="w",
        ).grid(row=row, column=2, sticky="w")
        sb.bind("<FocusOut>", lambda e: write_settings_from_vars())
        sb.bind("<Return>", lambda e: write_settings_from_vars())
        spinboxes.append(sb)

    add_setting_row(0, "Break duration", break_var, 1, 240, "minutes")
    add_setting_row(1, "Cooldown after break", cooldown_var, 0, 240, "minutes")
    add_setting_row(2, "Challenge word count", words_var, 1, len(wordlist), "words")
    tk.Label(
        s_inner, text="Saves on focus-out, Enter, or arrow click.",
        bg=WHITE, fg=INK3, font=F("sans", 10, "italic"), anchor="w",
    ).pack(anchor="w")

    launch_card = tk.Frame(
        s_inner, bg=PAPER,
        highlightthickness=1, highlightbackground=LINE,
    )
    launch_card.pack(fill=tk.X, pady=(18, 0))
    launch_pad = tk.Frame(launch_card, bg=PAPER)
    launch_pad.pack(fill=tk.X, padx=28, pady=20)
    tk.Label(
        launch_pad, text="Launch at login", bg=PAPER, fg=INK,
        font=F("serif", 16), anchor="w",
    ).pack(anchor="w")
    launch_var = tk.BooleanVar(value=is_launch_at_login_installed())
    launch_status_var = tk.StringVar(value="")

    def toggle_launch_at_login() -> None:
        if launch_var.get():
            ok, msg = install_launch_at_login()
            if ok:
                launch_status_var.set(f"Installed at: {msg}")
            else:
                launch_var.set(False)
                launch_status_var.set(f"Failed: {msg}")
        else:
            ok, msg = uninstall_launch_at_login()
            if ok:
                launch_status_var.set("Removed.")
            else:
                launch_var.set(True)
                launch_status_var.set(f"Failed: {msg}")

    tk.Checkbutton(
        launch_pad, text="Run on login", variable=launch_var,
        command=toggle_launch_at_login,
        bg=PAPER, fg=INK, font=F("sans", 11),
        activebackground=PAPER, selectcolor=WHITE,
        highlightthickness=0, anchor="w",
    ).pack(anchor="w", pady=(8, 0))
    tk.Label(
        launch_pad, textvariable=launch_status_var, bg=PAPER, fg=INK2,
        font=F("sans", 10, "italic"), wraplength=700, justify="left",
        anchor="w",
    ).pack(anchor="w", pady=(4, 0))

    s_diag_var = tk.StringVar(value="")
    tk.Label(
        s_inner, textvariable=s_diag_var, bg=WHITE, fg=INK3,
        font=F("mono", 9), anchor="w", justify="left",
    ).pack(anchor="w", pady=(20, 0))

    load_settings_from_config(killer.snapshot()["config"])

    # ---- Show first page ----
    set_page("today")

    # ---- Refresh loop ----
    def refresh() -> None:
        snap = killer.snapshot()
        cfg = snap["config"]
        window = snap["active_window"]
        now = datetime.now()
        ends_at = killer.break_ends_at()

        today_date_var.set(now.strftime("%A, %B %d").upper())

        if ends_at and now < ends_at:
            remaining = (ends_at - now).total_seconds()
            pill_var.set("BREAK ACTIVE")
            pill_dot.config(bg=OK_GREEN)
            pill_label.config(fg=OK_GREEN)
            hero_session_var.set("Allowance break")
            hero_meta_var.set(f"Ends at {ends_at.strftime('%H:%M')}")
            hero_time_var.set(_format_remaining(remaining))
        elif window:
            is_manual = window.get("source") == "manual"
            pill_var.set("FOCUS SESSION" if is_manual else "BLOCKING NOW")
            pill_dot.config(bg=ACCENT)
            pill_label.config(fg=ACCENT)
            hero_session_var.set("Focus session" if is_manual else "Deep work")
            try:
                _w_start = datetime.fromisoformat(window["start"]).strftime("%H:%M")
                _w_end = datetime.fromisoformat(window["end"]).strftime("%H:%M")
                hero_meta_var.set(f"{_w_start} – {_w_end}")
            except (KeyError, ValueError):
                hero_meta_var.set(
                    "Focus session · in progress" if is_manual
                    else "Deep work · in progress"
                )
            try:
                end_dt = datetime.fromisoformat(window["end"])
                # Calendar events arrive tz-aware; `now` is naive. Drop tzinfo
                # so subtraction doesn't raise (same fix pattern as
                # _summarize_calendar_today, see commit e9074c6).
                if end_dt.tzinfo is not None:
                    end_dt = end_dt.replace(tzinfo=None)
                rem = (end_dt - now).total_seconds()
                hero_time_var.set(_format_remaining(rem) if rem > 0 else "—")
            except Exception:
                hero_time_var.set("—")
        else:
            pill_var.set("CLEAR")
            pill_dot.config(bg=INK3)
            pill_label.config(fg=INK3)
            hero_session_var.set("No active block")
            hero_meta_var.set(_summarize_calendar_today(now))
            hero_time_var.set("—")

        ok, _reason = killer.can_take_break()
        set_button_enabled(break_btn, ok and not ends_at)

        cd_remaining = killer.cooldown_remaining_seconds()
        if cd_remaining > 0 and not ends_at:
            allowance_caption_var.set(
                f"Allowance available in {_format_remaining(cd_remaining)}")
        else:
            allowance_caption_var.set("")

        focus_blocked = bool(window) or bool(ends_at and now < ends_at)
        set_button_enabled(focus_30_btn, not focus_blocked)
        set_button_enabled(focus_60_btn, not focus_blocked)

        if window:
            sb_label_var.set(
                "Focus session" if window.get("source") == "manual"
                else "Deep work"
            )
            try:
                _sb_end = datetime.fromisoformat(window["end"]).strftime("%H:%M")
                sb_sub_var.set(f"ends {_sb_end}")
            except (KeyError, ValueError):
                sb_sub_var.set("active")
        else:
            sb_label_var.set("None")
            sb_sub_var.set(_summarize_calendar_today(now))

        kills = snap["kills"]
        last_tick = snap["last_tick_at"]
        method = snap["method"] or "(none yet)"
        uptime = time.monotonic() - started_at
        stat_kills_var.set(str(kills))
        stat_kills_sub_var.set(f"via {method}")
        if uptime >= 3600:
            stat_uptime_var.set(f"{int(uptime // 3600)}h")
        elif uptime >= 60:
            stat_uptime_var.set(f"{int(uptime // 60)}m")
        else:
            stat_uptime_var.set(f"{int(uptime)}s")
        stat_uptime_sub_var.set("uptime")
        cd = killer.cooldown_remaining_seconds()
        if ends_at:
            stat_cooldown_var.set(_format_remaining(
                (ends_at - now).total_seconds()))
            stat_cooldown_sub_var.set("break left")
        elif cd > 0:
            stat_cooldown_var.set(_format_remaining(cd))
            stat_cooldown_sub_var.set("cooldown")
        elif window:
            stat_cooldown_var.set("ready")
            stat_cooldown_sub_var.set("eligible")
        else:
            stat_cooldown_var.set("—")
            stat_cooldown_sub_var.set("no active block")

        last_killed = snap["last_killed"]
        if last_killed:
            last_killed_var.set("\n".join(last_killed[-6:]))
        else:
            last_killed_var.set("No kills yet.")

        if last_tick == 0:
            diag_var.set("Killer thread starting…")
        else:
            ago = max(0.0, time.monotonic() - last_tick)
            diag_var.set(
                f"last tick {ago:.1f}s ago · enum {method} · "
                f"uptime {uptime:.0f}s · python "
                f"{sys.version.split()[0]} on "
                f"{platform.system()} {platform.release()}"
            )
        err = snap["config_error"]
        err_var.set(f"Config error: {err}" if err else "")
        s_diag_var.set(
            f"Wordlist: {len(wordlist)} words ({wordlist_source})\n"
            f"Config: {config_path()}\n"
            f"State:  {state_path()}"
        )

        refresh_apps_list()
        refresh_calendar_page()

        locked = killer.is_edit_locked()
        edit_remaining = killer.edit_unlock_remaining_seconds()
        edit_buttons = (apps_add_btn, apps_remove_btn)
        if locked:
            if not blocks_lock_banner.winfo_ismapped():
                blocks_lock_banner.pack(
                    fill=tk.X, pady=(0, 12), before=blocks_card)
            for b in edit_buttons:
                set_button_enabled(b, False)
        else:
            if blocks_lock_banner.winfo_ismapped():
                blocks_lock_banner.pack_forget()
            for b in edit_buttons:
                set_button_enabled(b, True)
            if edit_remaining > 0:
                rem = (
                    f"Edit access: {_format_remaining(edit_remaining)} "
                    f"remaining"
                )
                blocks_lock_label.config(text=rem)
            else:
                blocks_lock_label.config(
                    text="List frozen during active block.")

        focused = root.focus_get()
        if focused not in spinboxes:
            load_settings_from_config(cfg)

        root.after(500, refresh)

    _startup_cfg = killer.snapshot()["config"]
    _cal_cfg = _startup_cfg.get("calendar", {})
    _additional = _cal_cfg.get("additionalCalendars", []) or []
    if not isinstance(_additional, list):
        _additional = []
    outlook_calendar.start_background_sync(
        interval_seconds=int(_cal_cfg.get("syncIntervalSeconds", 60)),
        category=str(_cal_cfg.get("deepWorkCategory", "Deep Work")),
        additional_calendars=[str(n) for n in _additional if str(n).strip()],
    )
    refresh()
    root.mainloop()


if __name__ == "__main__":
    main()
