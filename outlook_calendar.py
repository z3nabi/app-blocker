"""Outlook calendar integration — replaces the static schedule.

Public API:
    current_deep_work_event(now) -> dict | None
    last_sync_status() -> dict
    force_refresh() -> None
    start_background_sync(interval_seconds=60) -> None

Reads today's calendar events tagged with the configured category
("Deep Work" by default) from a running Outlook instance via COM,
caches them in-memory and to disk, and exposes a single function the
blocker tick loop calls to decide block/unblock.

Never launches Outlook (uses GetActiveObject, not EnsureDispatch /
Dispatch) — Outlook itself is a blocked app and self-launching it
would create a kill/relaunch loop.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, date, time, timedelta
from pathlib import Path

try:
    import win32com.client  # type: ignore
    import pywintypes  # type: ignore
    HAVE_WIN32 = True
except ImportError:
    HAVE_WIN32 = False


def _event_has_category(categories_field: str | None, target: str) -> bool:
    """Return True if `target` appears as a whole token in Outlook's
    comma-separated Categories string. Case-sensitive."""
    if not categories_field:
        return False
    tokens = [t.strip() for t in categories_field.split(",")]
    return target in tokens


def _event_covers(event: dict, now: datetime) -> bool:
    """Return True if `now` falls within [event.start, event.end).

    All-day events use [00:00 of start_date, 23:59:59.999999 of (end_date - 1 day)].
    Outlook represents an all-day event ending on day D as having end=D+1 00:00,
    so we subtract one microsecond from end to get a closed-on-end-day comparison.
    """
    try:
        start = datetime.fromisoformat(event["start"]).replace(tzinfo=None)
        end = datetime.fromisoformat(event["end"]).replace(tzinfo=None)
    except (KeyError, ValueError):
        return False

    if event.get("isAllDay"):
        # Outlook all-day events: end is the day AFTER the last covered day at 00:00.
        # Treat as covering up to (end - 1 microsecond).
        end = end - timedelta(microseconds=1)
        return start <= now <= end

    return start <= now < end


_EMPTY_CACHE = {
    "lastSyncAt": None,
    "lastSyncOk": False,
    "lastSyncError": None,
    "events": [],
}


def _load_cache(path: Path) -> dict:
    """Load cache from disk; return empty cache on missing file or invalid JSON."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(_EMPTY_CACHE, events=[])
    # Defensive: if the file is missing keys or has wrong types, fall back to defaults.
    raw_events = data.get("events")
    events = list(raw_events) if isinstance(raw_events, list) else []
    return {
        "lastSyncAt": data.get("lastSyncAt"),
        "lastSyncOk": bool(data.get("lastSyncOk", False)),
        "lastSyncError": data.get("lastSyncError"),
        "events": events,
    }


def _save_cache(path: Path, cache: dict) -> None:
    """Atomically write cache to disk (write-temp-then-rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


import threading


# In-memory cache + lock. Initialized to empty; populated by sync thread on startup.
_cache_lock = threading.Lock()
_cache: dict = dict(_EMPTY_CACHE, events=[])


def current_deep_work_event(now: datetime) -> dict | None:
    """Return the first cached event covering `now`, or None.

    This is the function the blocker tick loop calls. It must be cheap
    (in-memory, no I/O, no COM) and must never raise.
    """
    with _cache_lock:
        events = list(_cache.get("events", []))
    for event in events:
        if _event_covers(event, now):
            return dict(event)
    return None


def _reset_for_tests() -> None:
    """Wipe in-memory cache. Test-only."""
    global _cache
    with _cache_lock:
        _cache = dict(_EMPTY_CACHE, events=[])


def _set_cache_for_tests(cache: dict) -> None:
    """Set in-memory cache. Test-only. Deep-copies events list to avoid aliasing."""
    global _cache
    with _cache_lock:
        _cache = dict(cache, events=[dict(ev) for ev in cache.get("events", [])])


class OutlookNotRunning(Exception):
    """Raised when GetActiveObject can't find a running Outlook."""


def _get_active_outlook():
    """Return a running Outlook Application via COM, or raise OutlookNotRunning.

    NEVER uses Dispatch / EnsureDispatch — those auto-launch Outlook, which
    would create a kill/relaunch loop because Outlook is itself a blocked app.
    """
    if not HAVE_WIN32 or sys.platform != "win32":
        raise OutlookNotRunning()
    try:
        return win32com.client.GetActiveObject("Outlook.Application")
    except pywintypes.com_error:
        raise OutlookNotRunning()


def _fetch_today_events_from_outlook(outlook_app, today: date, category: str) -> list[dict]:
    """Read today's calendar events from a running Outlook instance.

    `outlook_app` is the Outlook Application COM object — passed in so this
    function can be unit-tested with a mock without importing win32com.

    Returns a list of plain-dict events (no COM references); callers can
    cache them, persist them, etc., without keeping Outlook open.

    Internal exceptions while reading individual items are swallowed —
    a single corrupted item must not abort the whole sync.
    """
    namespace = outlook_app.GetNamespace("MAPI")
    calendar = namespace.GetDefaultFolder(9)  # 9 = olFolderCalendar
    items = calendar.Items

    # Order matters: Sort BEFORE setting IncludeRecurrences = True; both BEFORE Restrict.
    # This is what makes recurring events expand into individual instances inside the date filter.
    items.Sort("[Start]")
    items.IncludeRecurrences = True

    # Outlook's Restrict date format is locale-sensitive. en-US format works on the
    # work laptop; if the date format ever bites, this is the line to revisit.
    start_str = today.strftime("%m/%d/%Y 00:00")
    end_str = (today + timedelta(days=1)).strftime("%m/%d/%Y 00:00")
    restricted = items.Restrict(f"[Start] >= '{start_str}' AND [Start] < '{end_str}'")

    out: list[dict] = []
    item = restricted.GetFirst()
    while item is not None:
        try:
            if item.Class == 26:  # olAppointment
                if _event_has_category(item.Categories, category):
                    out.append({
                        "start": item.Start.isoformat() if hasattr(item.Start, "isoformat")
                                 else str(item.Start),
                        "end": item.End.isoformat() if hasattr(item.End, "isoformat")
                               else str(item.End),
                        "subject": item.Subject or "",
                        "isAllDay": bool(item.AllDayEvent),
                    })
        except Exception:
            # Per spec — skip unreadable items, never abort the loop.
            pass
        item = restricted.GetNext()
    return out


def _try_sync(cache_path: Path, category: str) -> None:
    """Attempt one sync. Update in-memory cache + disk on success;
    update last_sync_status either way. Never raises."""
    global _cache
    try:
        outlook_app = _get_active_outlook()
    except OutlookNotRunning:
        _update_status(ok=False, error="Outlook not open")
        return
    except Exception as e:
        _update_status(ok=False, error=f"Sync error: {e}")
        return

    try:
        events = _fetch_today_events_from_outlook(outlook_app, date.today(), category)
    except Exception as e:
        _update_status(ok=False, error=f"Sync error: {e}")
        return

    now_iso = datetime.now().replace(microsecond=0).isoformat()
    new_cache = {
        "lastSyncAt": now_iso,
        "lastSyncOk": True,
        "lastSyncError": None,
        "events": events,
    }
    with _cache_lock:
        _cache = new_cache
    try:
        _save_cache(cache_path, new_cache)
    except Exception:
        # Disk write or serialization failure is non-fatal — in-memory cache is still updated.
        pass


def _update_status(*, ok: bool, error: str | None) -> None:
    global _cache
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    with _cache_lock:
        _cache = dict(_cache)
        _cache["lastSyncAt"] = now_iso
        _cache["lastSyncOk"] = ok
        _cache["lastSyncError"] = error


def last_sync_status() -> dict:
    """Public: { 'at': iso_str|None, 'ok': bool, 'error': str|None }."""
    with _cache_lock:
        return {
            "at": _cache.get("lastSyncAt"),
            "ok": bool(_cache.get("lastSyncOk", False)),
            "error": _cache.get("lastSyncError"),
        }


def _get_cache_for_tests() -> dict:
    """Snapshot of in-memory cache. Test-only."""
    with _cache_lock:
        return dict(_cache)
