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
from datetime import datetime, date, timedelta
from pathlib import Path

_WIN32_IMPORT_ERROR: str | None = None
try:
    import win32com.client  # type: ignore
    import pywintypes  # type: ignore
    HAVE_WIN32 = True
except ImportError as _e:
    HAVE_WIN32 = False
    _WIN32_IMPORT_ERROR = str(_e)

_TRACE_ENABLED = os.environ.get("OUTLOOK_CALENDAR_TRACE", "1") != "0"


def _trace(msg: str) -> None:
    """Diagnostic trace to stderr. Prefixed so the user can grep the console.

    Disabled by setting `outlook_calendar._TRACE_ENABLED = False` (used by tests
    to keep stderr clean), or by setting env var OUTLOOK_CALENDAR_TRACE=0 before
    the module is imported.
    """
    if not _TRACE_ENABLED:
        return
    print(f"[outlook_calendar] {msg}", file=sys.stderr, flush=True)


_trace(
    f"module load: HAVE_WIN32={HAVE_WIN32}, sys.platform={sys.platform!r}"
    + (f", import_error={_WIN32_IMPORT_ERROR!r}" if _WIN32_IMPORT_ERROR else "")
)


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


def events_on_date(events: list[dict], target: date) -> list[tuple[datetime, dict]]:
    """Return (start, event) pairs whose start falls on `target`, sorted by start.

    Strips tzinfo so date comparison matches the local-naive convention used
    elsewhere (datetime.now(), date.today()). Skips entries with missing or
    malformed start fields.

    Necessary because the cache file persists across days: if no successful
    sync has run today, the cache may still hold events from a prior day.
    """
    out: list[tuple[datetime, dict]] = []
    for ev in events:
        try:
            start = datetime.fromisoformat(ev["start"]).replace(tzinfo=None)
        except (KeyError, TypeError, ValueError):
            continue
        if start.date() == target:
            out.append((start, ev))
    out.sort(key=lambda p: p[0])
    return out


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
        _trace(
            f"_get_active_outlook: skipping (HAVE_WIN32={HAVE_WIN32}, "
            f"sys.platform={sys.platform!r})"
        )
        raise OutlookNotRunning()
    try:
        app = win32com.client.GetActiveObject("Outlook.Application")
        _trace("_get_active_outlook: GetActiveObject succeeded")
        return app
    except pywintypes.com_error as e:
        _trace(f"_get_active_outlook: GetActiveObject raised com_error: {e!r}")
        raise OutlookNotRunning()


def _fetch_events_from_folder(folder, today: date, category: str) -> list[dict]:
    """Read today's matching events from a single calendar folder.

    Internal exceptions while reading individual items are swallowed —
    a single corrupted item must not abort the whole sync.
    """
    items = folder.Items

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


def _resolve_additional_folders(default_calendar, names: list[str]) -> list:
    """Resolve additional calendar folders by name (case-insensitive).

    Looks for matches as subfolders of the default Calendar and as siblings
    at the mailbox root. Names that don't match anything are logged and
    skipped — never raised.
    """
    if not names:
        return []

    candidates: dict[str, object] = {}

    def _index(folder_iter) -> None:
        try:
            for f in folder_iter:
                try:
                    name = str(f.Name).strip()
                    if name:
                        candidates.setdefault(name.lower(), f)
                except Exception:
                    continue
        except Exception:
            return

    # Subfolders of the default Calendar (typical for personal extra calendars).
    try:
        _index(default_calendar.Folders)
    except Exception:
        pass

    # Siblings at the mailbox root (e.g. calendars created at the top level).
    try:
        parent = default_calendar.Parent
        default_name_lc = str(default_calendar.Name).lower() if default_calendar.Name else None
        for sib in parent.Folders:
            try:
                sib_name = str(sib.Name).strip()
                if sib_name and sib_name.lower() != default_name_lc:
                    candidates.setdefault(sib_name.lower(), sib)
            except Exception:
                continue
    except Exception:
        pass

    resolved = []
    for name in names:
        match = candidates.get(name.lower())
        if match is None:
            _trace(f"_resolve_additional_folders: no calendar named {name!r}")
            continue
        resolved.append(match)
    return resolved


def _fetch_today_events_from_outlook(
    outlook_app, today: date, category: str,
    *, additional_calendars: list[str] | tuple[str, ...] = (),
) -> list[dict]:
    """Read today's calendar events from a running Outlook instance.

    `outlook_app` is the Outlook Application COM object — passed in so this
    function can be unit-tested with a mock without importing win32com.

    `additional_calendars` are names of secondary calendars to scan in
    addition to the default; missing names are skipped silently (with a
    trace log) so a typo doesn't break sync.

    Returns a list of plain-dict events (no COM references); callers can
    cache them, persist them, etc., without keeping Outlook open.
    """
    namespace = outlook_app.GetNamespace("MAPI")
    default = namespace.GetDefaultFolder(9)  # 9 = olFolderCalendar

    folders = [default]
    folders.extend(_resolve_additional_folders(default, list(additional_calendars)))

    out: list[dict] = []
    for folder in folders:
        try:
            out.extend(_fetch_events_from_folder(folder, today, category))
        except Exception as e:
            _trace(f"_fetch_today_events_from_outlook: folder fetch error {type(e).__name__}: {e}")
            continue

    _trace(
        f"_fetch_today_events_from_outlook: scanned {len(folders)} folder(s), "
        f"matched {len(out)} on category {category!r}"
    )
    return out


def _try_sync(
    cache_path: Path, category: str,
    *, additional_calendars: list[str] | tuple[str, ...] = (),
) -> None:
    """Attempt one sync. Update in-memory cache + disk on success;
    update last_sync_status either way. Never raises."""
    global _cache
    _trace(
        f"_try_sync: starting (cache_path={cache_path}, category={category!r}, "
        f"additional_calendars={list(additional_calendars)!r})"
    )
    try:
        outlook_app = _get_active_outlook()
    except OutlookNotRunning:
        _trace("_try_sync: Outlook not open; cache untouched")
        _update_status(ok=False, error="Outlook not open")
        return
    except Exception as e:
        _trace(f"_try_sync: connect error {type(e).__name__}: {e}")
        _update_status(ok=False, error=f"Sync error: {e}")
        return

    try:
        events = _fetch_today_events_from_outlook(
            outlook_app, date.today(), category,
            additional_calendars=additional_calendars,
        )
    except Exception as e:
        _trace(f"_try_sync: fetch error {type(e).__name__}: {e}")
        _update_status(ok=False, error=f"Sync error: {e}")
        return

    _trace(f"_try_sync: fetched {len(events)} matching event(s)")

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
    except Exception as e:
        _trace(f"_try_sync: disk save failed (non-fatal): {type(e).__name__}: {e}")
        # Disk write or serialization failure is non-fatal — in-memory cache is still updated.
        pass
    else:
        _trace("_try_sync: cache persisted to disk")


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


def _snapshot_cache() -> dict:
    """Return a shallow snapshot of the in-memory cache (private API for the UI)."""
    with _cache_lock:
        return dict(_cache)


# Sentinel: the daemon thread (or None if not started).
_sync_thread: threading.Thread | None = None
_sync_thread_lock = threading.Lock()
_sync_wakeup = threading.Event()
_sync_stop = threading.Event()


def _sync_loop(
    cache_path: Path, category: str, interval_seconds: int,
    additional_calendars: tuple[str, ...],
) -> None:
    """Daemon loop: sync, sleep, repeat. Wakes early if force_refresh fires."""
    while not _sync_stop.is_set():
        try:
            _try_sync(
                cache_path=cache_path, category=category,
                additional_calendars=additional_calendars,
            )
        except Exception:
            # _try_sync should never raise, but defense-in-depth.
            pass
        # Sleep up to interval_seconds, but wake immediately on force_refresh.
        _sync_wakeup.wait(timeout=interval_seconds)
        _sync_wakeup.clear()


def start_background_sync(
    *,
    interval_seconds: int = 60,
    cache_path: Path | None = None,
    category: str = "Deep Work",
    additional_calendars: list[str] | tuple[str, ...] = (),
) -> None:
    """Start the daemon refresh thread. Idempotent: safe to call multiple times."""
    global _sync_thread
    with _sync_thread_lock:
        if _sync_thread is not None and _sync_thread.is_alive():
            return
        if cache_path is None:
            cache_path = Path.home() / ".app-blocker" / "calendar-cache.json"
        # Pre-load on-disk cache so the first tick has data even before the first sync completes.
        loaded = _load_cache(cache_path)
        global _cache
        with _cache_lock:
            _cache = loaded
        _sync_stop.clear()
        _sync_wakeup.clear()
        t = threading.Thread(
            target=_sync_loop,
            kwargs={
                "cache_path": cache_path,
                "category": category,
                "interval_seconds": interval_seconds,
                "additional_calendars": tuple(additional_calendars),
            },
            name="outlook-calendar-sync",
            daemon=True,
        )
        _sync_thread = t
        t.start()


def force_refresh() -> None:
    """Wake the sync thread to run a sync immediately. No-op if thread not started."""
    _sync_wakeup.set()


def _stop_background_sync_for_tests() -> None:
    """Test-only: signal the sync thread to exit and join it."""
    global _sync_thread
    with _sync_thread_lock:
        if _sync_thread is None:
            return
        _sync_stop.set()
        _sync_wakeup.set()  # wake it so it sees the stop flag
        _sync_thread.join(timeout=2.0)
        _sync_thread = None


def _is_background_running_for_tests() -> bool:
    with _sync_thread_lock:
        return _sync_thread is not None and _sync_thread.is_alive()
