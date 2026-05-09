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
