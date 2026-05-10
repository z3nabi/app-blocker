"""KillerThread — background loop that enforces blocked apps during deep work."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta

import outlook_calendar
from paths import (
    EDIT_UNLOCK_MINUTES,
    config_path,
    load_or_create_config,
    load_state,
    save_state,
)
from processes import (
    _normalize,
    collect_blocked_normalized,
    kill_pid,
    list_processes,
)


TICK_INTERVAL = 1.0


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
