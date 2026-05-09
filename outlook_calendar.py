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
