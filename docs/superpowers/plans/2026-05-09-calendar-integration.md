# Calendar Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static day/HH:MM `schedule` config with a calendar-driven rule: block when an Outlook event tagged with the "Deep Work" category covers the current moment.

**Architecture:** New module `outlook_calendar.py` owns Outlook/COM concerns and a today-events cache (in-memory + persisted to `~/.app-blocker/calendar-cache.json`). A daemon thread refreshes the cache every 60s via `win32com.client.GetActiveObject` (never `EnsureDispatch` — Outlook itself is a blocked app and must never be auto-launched). `main.py` replaces calls to `active_window(now, schedule)` with `current_deep_work_event(now)`; a non-`None` return means "block now."

**Tech Stack:** Python 3.9 stdlib + `pywin32` (already on the work laptop). Tests use stdlib `unittest`. UI is Tkinter (existing). No new third-party deps.

**Spec:** `docs/superpowers/specs/2026-05-09-calendar-integration-design.md`

**Reference (temporary):** `gencache_example.py` at the repo root — the user's existing working Outlook integration. Will be deleted in the final task.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `outlook_calendar.py` | Create | Public API for the rest of the app: `current_deep_work_event`, `last_sync_status`, `force_refresh`, `start_background_sync`. Private helpers for parsing/cache/COM fetch. |
| `tests/__init__.py` | Create | Empty — makes `tests/` a package so `python -m unittest tests.test_outlook_calendar` works. |
| `tests/test_outlook_calendar.py` | Create | Unit tests for pure helpers + COM-fetch with a mocked Outlook app object. |
| `main.py` | Modify | Drop `active_window`, drop `"schedule"` from `DEFAULT_CONFIG`, add `"calendar"` defaults, wire tick loop and edit-lock to `current_deep_work_event`, replace Schedule UI page with a Calendar page, delete `ScheduleWindowEditor`, repoint `_summarize_schedule_today`. |
| `README.md` | Modify | Mention `pywin32` requirement on Windows. |
| `gencache_example.py` | Delete | Temporary reference — remove once `outlook_calendar.py` is committed. |

---

## Task 1: Scaffolding (test framework + module skeleton)

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_outlook_calendar.py`
- Create: `outlook_calendar.py`

- [ ] **Step 1: Create empty test package init**

Write to `tests/__init__.py`:
```python
```
(Empty file.)

- [ ] **Step 2: Create the module skeleton**

Write to `outlook_calendar.py`:
```python
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
```

- [ ] **Step 3: Write a smoke test**

Write to `tests/test_outlook_calendar.py`:
```python
"""Tests for outlook_calendar — pure helpers + mocked COM fetch.

Designed to run on macOS (dev) and Windows (deploy). Tests do not
import or call win32com; the COM-fetch test injects a mock Outlook
application object directly into the function under test.
"""

import unittest

import outlook_calendar


class TestModuleImport(unittest.TestCase):
    def test_module_imports_cleanly(self):
        self.assertTrue(hasattr(outlook_calendar, "HAVE_WIN32"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the smoke test**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar -v`
Expected: `Ran 1 test in 0.000s` `OK`. (On macOS, `HAVE_WIN32` is `False`. On Windows with pywin32 installed, `True`. Either is fine for this test.)

- [ ] **Step 5: Commit**

```bash
git -C /Users/simon/repos/app-blocker add outlook_calendar.py tests/__init__.py tests/test_outlook_calendar.py
git -C /Users/simon/repos/app-blocker commit -m "Add outlook_calendar module skeleton + test scaffolding"
```

---

## Task 2: `_event_has_category` (pure helper)

Outlook's `Categories` field is a string of comma-separated tokens (e.g. `"Deep Work, Personal"`). We need a case-sensitive token match — substring matching would let `"Deep Work"` accidentally match a hypothetical `"Pre-Deep Work"` category.

**Files:**
- Modify: `tests/test_outlook_calendar.py` (add test class)
- Modify: `outlook_calendar.py` (add helper)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_outlook_calendar.py`:
```python
class TestEventHasCategory(unittest.TestCase):
    def test_single_category_match(self):
        self.assertTrue(outlook_calendar._event_has_category("Deep Work", "Deep Work"))

    def test_multi_category_match(self):
        self.assertTrue(outlook_calendar._event_has_category("Personal, Deep Work", "Deep Work"))

    def test_multi_category_no_match(self):
        self.assertFalse(outlook_calendar._event_has_category("Personal, Meeting", "Deep Work"))

    def test_token_with_surrounding_whitespace(self):
        self.assertTrue(outlook_calendar._event_has_category("  Deep Work  ,Personal", "Deep Work"))

    def test_case_sensitive(self):
        self.assertFalse(outlook_calendar._event_has_category("deep work", "Deep Work"))

    def test_empty_categories(self):
        self.assertFalse(outlook_calendar._event_has_category("", "Deep Work"))

    def test_none_categories(self):
        self.assertFalse(outlook_calendar._event_has_category(None, "Deep Work"))

    def test_substring_does_not_match(self):
        # "Pre-Deep Work" should not match "Deep Work" — token boundary.
        self.assertFalse(outlook_calendar._event_has_category("Pre-Deep Work", "Deep Work"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestEventHasCategory -v`
Expected: FAIL with `AttributeError: module 'outlook_calendar' has no attribute '_event_has_category'`.

- [ ] **Step 3: Implement the helper**

Append to `outlook_calendar.py`:
```python
def _event_has_category(categories_field: str | None, target: str) -> bool:
    """Return True if `target` appears as a whole token in Outlook's
    comma-separated Categories string. Case-sensitive."""
    if not categories_field:
        return False
    tokens = [t.strip() for t in categories_field.split(",")]
    return target in tokens
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestEventHasCategory -v`
Expected: `Ran 8 tests in 0.000s` `OK`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/simon/repos/app-blocker add outlook_calendar.py tests/test_outlook_calendar.py
git -C /Users/simon/repos/app-blocker commit -m "outlook_calendar: _event_has_category with token-match semantics"
```

---

## Task 3: `_event_covers` + all-day expansion

The blocking decision asks: does this event cover the current moment? Timed events compare ISO start/end. All-day events expand to `00:00 of start_date` through `23:59:59 of end_date` so a multi-day all-day Deep Work block covers every moment in its span.

**Files:**
- Modify: `tests/test_outlook_calendar.py`
- Modify: `outlook_calendar.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_outlook_calendar.py`:
```python
class TestEventCovers(unittest.TestCase):
    def _ev(self, start, end, all_day=False):
        return {"start": start, "end": end, "subject": "x", "isAllDay": all_day}

    def test_covers_strictly_inside(self):
        ev = self._ev("2026-05-09T09:00:00", "2026-05-09T11:00:00")
        self.assertTrue(outlook_calendar._event_covers(ev, datetime(2026, 5, 9, 10, 0, 0)))

    def test_now_equals_start_is_covered(self):
        ev = self._ev("2026-05-09T09:00:00", "2026-05-09T11:00:00")
        self.assertTrue(outlook_calendar._event_covers(ev, datetime(2026, 5, 9, 9, 0, 0)))

    def test_now_equals_end_is_not_covered(self):
        # Half-open [start, end) — end-time stops blocking.
        ev = self._ev("2026-05-09T09:00:00", "2026-05-09T11:00:00")
        self.assertFalse(outlook_calendar._event_covers(ev, datetime(2026, 5, 9, 11, 0, 0)))

    def test_before_start_not_covered(self):
        ev = self._ev("2026-05-09T09:00:00", "2026-05-09T11:00:00")
        self.assertFalse(outlook_calendar._event_covers(ev, datetime(2026, 5, 9, 8, 59, 59)))

    def test_all_day_single_day_covers_morning(self):
        # All-day event for 2026-05-09 covers any time on 2026-05-09.
        ev = self._ev("2026-05-09T00:00:00", "2026-05-10T00:00:00", all_day=True)
        self.assertTrue(outlook_calendar._event_covers(ev, datetime(2026, 5, 9, 7, 30, 0)))
        self.assertTrue(outlook_calendar._event_covers(ev, datetime(2026, 5, 9, 23, 59, 59)))

    def test_all_day_single_day_does_not_cover_next_day(self):
        ev = self._ev("2026-05-09T00:00:00", "2026-05-10T00:00:00", all_day=True)
        self.assertFalse(outlook_calendar._event_covers(ev, datetime(2026, 5, 10, 0, 0, 0)))

    def test_all_day_multi_day_covers_middle(self):
        # 3-day all-day event 5/9 through 5/11.
        ev = self._ev("2026-05-09T00:00:00", "2026-05-12T00:00:00", all_day=True)
        self.assertTrue(outlook_calendar._event_covers(ev, datetime(2026, 5, 10, 12, 0, 0)))
        self.assertTrue(outlook_calendar._event_covers(ev, datetime(2026, 5, 11, 23, 59, 59)))

    def test_malformed_start_returns_false(self):
        ev = self._ev("not-a-date", "2026-05-09T11:00:00")
        self.assertFalse(outlook_calendar._event_covers(ev, datetime(2026, 5, 9, 10, 0, 0)))
```

Also add `from datetime import datetime` to the top of the test file:
```python
from datetime import datetime
```
(Place this with the other imports.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestEventCovers -v`
Expected: FAIL with `AttributeError: module 'outlook_calendar' has no attribute '_event_covers'`.

- [ ] **Step 3: Implement `_event_covers`**

Append to `outlook_calendar.py`:
```python
def _event_covers(event: dict, now: datetime) -> bool:
    """Return True if `now` falls within [event.start, event.end).

    All-day events use [00:00 of start_date, 23:59:59.999999 of (end_date - 1 day)].
    Outlook represents an all-day event ending on day D as having end=D+1 00:00,
    so we subtract one second from end to get a closed-on-end-day comparison.
    """
    try:
        start = datetime.fromisoformat(event["start"])
        end = datetime.fromisoformat(event["end"])
    except (KeyError, ValueError):
        return False

    if event.get("isAllDay"):
        # Outlook all-day events: end is the day AFTER the last covered day at 00:00.
        # Treat as covering up to (end - 1 microsecond).
        end = end - timedelta(microseconds=1)
        return start <= now <= end

    return start <= now < end
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestEventCovers -v`
Expected: `Ran 8 tests in 0.000s` `OK`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/simon/repos/app-blocker add outlook_calendar.py tests/test_outlook_calendar.py
git -C /Users/simon/repos/app-blocker commit -m "outlook_calendar: _event_covers with all-day expansion"
```

---

## Task 4: Cache load/save

`_load_cache(path)` returns the previous cache or an empty default. `_save_cache(path, cache)` writes atomically (write-temp-then-rename). Both must be safe to call when the file doesn't exist or contains invalid JSON.

**Files:**
- Modify: `tests/test_outlook_calendar.py`
- Modify: `outlook_calendar.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_outlook_calendar.py`:
```python
import json
import tempfile


class TestCacheIO(unittest.TestCase):
    def test_load_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            cache = outlook_calendar._load_cache(Path(d) / "missing.json")
            self.assertEqual(cache["events"], [])
            self.assertIsNone(cache["lastSyncAt"])
            self.assertFalse(cache["lastSyncOk"])

    def test_load_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text("{not valid json")
            cache = outlook_calendar._load_cache(p)
            self.assertEqual(cache["events"], [])

    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cache.json"
            original = {
                "lastSyncAt": "2026-05-09T08:30:00",
                "lastSyncOk": True,
                "lastSyncError": None,
                "events": [
                    {"start": "2026-05-09T09:00:00", "end": "2026-05-09T11:00:00",
                     "subject": "Focus", "isAllDay": False},
                ],
            }
            outlook_calendar._save_cache(p, original)
            loaded = outlook_calendar._load_cache(p)
            self.assertEqual(loaded, original)

    def test_save_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cache.json"
            outlook_calendar._save_cache(p, {"lastSyncAt": "first", "lastSyncOk": True,
                                             "lastSyncError": None, "events": []})
            outlook_calendar._save_cache(p, {"lastSyncAt": "second", "lastSyncOk": True,
                                             "lastSyncError": None, "events": []})
            loaded = outlook_calendar._load_cache(p)
            self.assertEqual(loaded["lastSyncAt"], "second")
```

Also add `from pathlib import Path` to the test file imports if it isn't already there:
```python
from pathlib import Path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestCacheIO -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement cache I/O**

Append to `outlook_calendar.py`:
```python
import json
import os


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
    # Defensive: if the file is missing keys, fall back to defaults.
    return {
        "lastSyncAt": data.get("lastSyncAt"),
        "lastSyncOk": bool(data.get("lastSyncOk", False)),
        "lastSyncError": data.get("lastSyncError"),
        "events": list(data.get("events", [])),
    }


def _save_cache(path: Path, cache: dict) -> None:
    """Atomically write cache to disk (write-temp-then-rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestCacheIO -v`
Expected: `Ran 4 tests in 0.0XXs` `OK`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/simon/repos/app-blocker add outlook_calendar.py tests/test_outlook_calendar.py
git -C /Users/simon/repos/app-blocker commit -m "outlook_calendar: cache load/save with atomic write"
```

---

## Task 5: `current_deep_work_event` public API

Walks the in-memory cache, returns any event covering `now`, or `None`. This is the function `main.py` calls every tick.

**Files:**
- Modify: `tests/test_outlook_calendar.py`
- Modify: `outlook_calendar.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_outlook_calendar.py`:
```python
class TestCurrentDeepWorkEvent(unittest.TestCase):
    def setUp(self):
        # Reset module state between tests.
        outlook_calendar._reset_for_tests()

    def test_empty_cache_returns_none(self):
        self.assertIsNone(outlook_calendar.current_deep_work_event(datetime(2026, 5, 9, 10, 0)))

    def test_event_covering_now_returned(self):
        outlook_calendar._set_cache_for_tests({
            "lastSyncAt": "2026-05-09T08:00:00",
            "lastSyncOk": True,
            "lastSyncError": None,
            "events": [
                {"start": "2026-05-09T09:00:00", "end": "2026-05-09T11:00:00",
                 "subject": "Focus", "isAllDay": False},
            ],
        })
        result = outlook_calendar.current_deep_work_event(datetime(2026, 5, 9, 10, 0))
        self.assertIsNotNone(result)
        self.assertEqual(result["subject"], "Focus")

    def test_no_event_covers_now_returns_none(self):
        outlook_calendar._set_cache_for_tests({
            "lastSyncAt": "2026-05-09T08:00:00",
            "lastSyncOk": True,
            "lastSyncError": None,
            "events": [
                {"start": "2026-05-09T09:00:00", "end": "2026-05-09T11:00:00",
                 "subject": "Focus", "isAllDay": False},
            ],
        })
        self.assertIsNone(outlook_calendar.current_deep_work_event(datetime(2026, 5, 9, 13, 0)))

    def test_returns_first_matching_when_multiple_overlap(self):
        # If two Deep Work events overlap (rare but possible), we just return one.
        outlook_calendar._set_cache_for_tests({
            "lastSyncAt": "2026-05-09T08:00:00",
            "lastSyncOk": True,
            "lastSyncError": None,
            "events": [
                {"start": "2026-05-09T09:00:00", "end": "2026-05-09T11:00:00",
                 "subject": "A", "isAllDay": False},
                {"start": "2026-05-09T10:00:00", "end": "2026-05-09T12:00:00",
                 "subject": "B", "isAllDay": False},
            ],
        })
        result = outlook_calendar.current_deep_work_event(datetime(2026, 5, 9, 10, 30))
        self.assertIsNotNone(result)
        self.assertIn(result["subject"], ("A", "B"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestCurrentDeepWorkEvent -v`
Expected: FAIL with `AttributeError` for `_reset_for_tests` / `current_deep_work_event`.

- [ ] **Step 3: Implement public API + test hooks**

Append to `outlook_calendar.py`:
```python
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
            return event
    return None


def _reset_for_tests() -> None:
    """Wipe in-memory cache. Test-only."""
    global _cache
    with _cache_lock:
        _cache = dict(_EMPTY_CACHE, events=[])


def _set_cache_for_tests(cache: dict) -> None:
    """Set in-memory cache. Test-only."""
    global _cache
    with _cache_lock:
        _cache = dict(cache)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestCurrentDeepWorkEvent -v`
Expected: `Ran 4 tests in 0.000s` `OK`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/simon/repos/app-blocker add outlook_calendar.py tests/test_outlook_calendar.py
git -C /Users/simon/repos/app-blocker commit -m "outlook_calendar: current_deep_work_event public API"
```

---

## Task 6: COM fetch (with mocked Outlook)

`_fetch_today_events_from_outlook(outlook_app, today, category)` is the only function that talks to a live Outlook object. It takes the Outlook Application as a parameter (dependency injection) so tests can pass a mock without importing `win32com`. Uses `Items.Sort("[Start]")` then `Items.IncludeRecurrences = True` then `Items.Restrict(...)` — that ordering is required by Outlook's COM API to make recurring events expand into instances within the date filter.

**Files:**
- Modify: `tests/test_outlook_calendar.py`
- Modify: `outlook_calendar.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_outlook_calendar.py`:
```python
from unittest.mock import MagicMock, PropertyMock


class TestFetchTodayEventsFromOutlook(unittest.TestCase):
    def _make_outlook(self, items):
        """Build a mock Outlook Application object whose calendar returns `items`."""
        outlook = MagicMock()
        ns = MagicMock()
        outlook.GetNamespace.return_value = ns
        calendar = MagicMock()
        ns.GetDefaultFolder.return_value = calendar

        items_collection = MagicMock()
        calendar.Items = items_collection
        # Restrict returns a new collection. Use the same mock for simplicity —
        # the test cares about iteration semantics, not the Restrict call itself.
        restricted = MagicMock()
        items_collection.Restrict.return_value = restricted

        # Simulate GetFirst/GetNext iteration over the supplied items.
        seq = list(items)
        idx = {"i": 0}

        def get_first():
            idx["i"] = 0
            return seq[0] if seq else None

        def get_next():
            idx["i"] += 1
            return seq[idx["i"]] if idx["i"] < len(seq) else None

        restricted.GetFirst.side_effect = get_first
        restricted.GetNext.side_effect = get_next
        return outlook

    def _make_appointment(self, *, subject, start, end, categories, all_day=False, klass=26):
        """Build a mock Outlook AppointmentItem."""
        item = MagicMock()
        item.Class = klass
        item.Subject = subject
        item.Start = start  # datetime; real COM exposes pywintypes.Time but MagicMock is fine here
        item.End = end
        item.Categories = categories
        item.AllDayEvent = all_day
        return item

    def test_returns_only_deep_work_appointments(self):
        outlook = self._make_outlook([
            self._make_appointment(
                subject="Focus", start=datetime(2026, 5, 9, 9, 0),
                end=datetime(2026, 5, 9, 11, 0), categories="Deep Work"),
            self._make_appointment(
                subject="Lunch", start=datetime(2026, 5, 9, 12, 0),
                end=datetime(2026, 5, 9, 13, 0), categories="Personal"),
            self._make_appointment(
                subject="Standup", start=datetime(2026, 5, 9, 14, 0),
                end=datetime(2026, 5, 9, 14, 30), categories=""),
        ])
        events = outlook_calendar._fetch_today_events_from_outlook(
            outlook, date(2026, 5, 9), "Deep Work")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["subject"], "Focus")
        self.assertEqual(events[0]["start"], "2026-05-09T09:00:00")
        self.assertEqual(events[0]["end"], "2026-05-09T11:00:00")
        self.assertFalse(events[0]["isAllDay"])

    def test_skips_non_appointment_class(self):
        outlook = self._make_outlook([
            self._make_appointment(
                subject="A meeting request, not an appointment",
                start=datetime(2026, 5, 9, 9, 0),
                end=datetime(2026, 5, 9, 11, 0),
                categories="Deep Work",
                klass=53),  # MeetingItem, not AppointmentItem (26)
        ])
        events = outlook_calendar._fetch_today_events_from_outlook(
            outlook, date(2026, 5, 9), "Deep Work")
        self.assertEqual(events, [])

    def test_corrupted_item_skipped_not_raised(self):
        bad_item = MagicMock()
        type(bad_item).Class = PropertyMock(side_effect=Exception("can't read"))
        good_item = self._make_appointment(
            subject="Focus", start=datetime(2026, 5, 9, 9, 0),
            end=datetime(2026, 5, 9, 11, 0), categories="Deep Work")
        outlook = self._make_outlook([bad_item, good_item])
        events = outlook_calendar._fetch_today_events_from_outlook(
            outlook, date(2026, 5, 9), "Deep Work")
        # Bad item skipped, good item kept.
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["subject"], "Focus")

    def test_calls_outlook_in_correct_order(self):
        outlook = self._make_outlook([])
        outlook_calendar._fetch_today_events_from_outlook(
            outlook, date(2026, 5, 9), "Deep Work")
        # Spec: Sort "[Start]" → IncludeRecurrences = True → Restrict(...).
        items_collection = outlook.GetNamespace.return_value.GetDefaultFolder.return_value.Items
        items_collection.Sort.assert_called_once_with("[Start]")
        # IncludeRecurrences set via attribute assignment — verify property was set.
        self.assertEqual(items_collection.IncludeRecurrences, True)
        items_collection.Restrict.assert_called_once()

    def test_all_day_event_marked(self):
        outlook = self._make_outlook([
            self._make_appointment(
                subject="Focus day", start=datetime(2026, 5, 9, 0, 0),
                end=datetime(2026, 5, 10, 0, 0), categories="Deep Work", all_day=True),
        ])
        events = outlook_calendar._fetch_today_events_from_outlook(
            outlook, date(2026, 5, 9), "Deep Work")
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["isAllDay"])
```

Add `from datetime import date` to the test imports (alongside `datetime`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestFetchTodayEventsFromOutlook -v`
Expected: FAIL with `AttributeError: module 'outlook_calendar' has no attribute '_fetch_today_events_from_outlook'`.

- [ ] **Step 3: Implement the COM fetch**

Append to `outlook_calendar.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestFetchTodayEventsFromOutlook -v`
Expected: `Ran 5 tests in 0.0XXs` `OK`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/simon/repos/app-blocker add outlook_calendar.py tests/test_outlook_calendar.py
git -C /Users/simon/repos/app-blocker commit -m "outlook_calendar: _fetch_today_events_from_outlook with mocked tests"
```

---

## Task 7: Sync orchestration + status

`_try_sync()` is the function the background thread calls. It connects to Outlook via `GetActiveObject` (NEVER `Dispatch` / `EnsureDispatch`), invokes the fetch, updates the in-memory cache, persists to disk. Captures errors into `last_sync_status` instead of raising.

**Files:**
- Modify: `tests/test_outlook_calendar.py`
- Modify: `outlook_calendar.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_outlook_calendar.py`:
```python
from unittest.mock import patch


class TestTrySync(unittest.TestCase):
    def setUp(self):
        outlook_calendar._reset_for_tests()

    def test_successful_sync_updates_cache_and_status(self):
        # Patch the GetActiveObject lookup so we don't need real win32com.
        fake_outlook = MagicMock()
        # Build a calendar that returns one Deep Work event today.
        ns = MagicMock()
        fake_outlook.GetNamespace.return_value = ns
        cal = MagicMock()
        ns.GetDefaultFolder.return_value = cal
        items = MagicMock()
        cal.Items = items
        restricted = MagicMock()
        items.Restrict.return_value = restricted
        appt = MagicMock()
        appt.Class = 26
        appt.Subject = "Focus"
        today = date.today()
        appt.Start = datetime.combine(today, datetime.min.time()).replace(hour=9)
        appt.End = datetime.combine(today, datetime.min.time()).replace(hour=11)
        appt.Categories = "Deep Work"
        appt.AllDayEvent = False
        restricted.GetFirst.return_value = appt
        restricted.GetNext.return_value = None

        with tempfile.TemporaryDirectory() as d:
            cache_path = Path(d) / "cache.json"
            with patch.object(outlook_calendar, "_get_active_outlook", return_value=fake_outlook):
                outlook_calendar._try_sync(cache_path=cache_path, category="Deep Work")

        status = outlook_calendar.last_sync_status()
        self.assertTrue(status["ok"])
        self.assertIsNone(status["error"])
        self.assertIsNotNone(status["at"])
        self.assertEqual(len(outlook_calendar._get_cache_for_tests()["events"]), 1)

    def test_outlook_not_running_leaves_cache_unchanged(self):
        # Pre-populate cache with one event.
        prior = {
            "lastSyncAt": "2026-05-09T07:00:00",
            "lastSyncOk": True,
            "lastSyncError": None,
            "events": [
                {"start": "2026-05-09T09:00:00", "end": "2026-05-09T11:00:00",
                 "subject": "Prior", "isAllDay": False},
            ],
        }
        outlook_calendar._set_cache_for_tests(prior)

        with tempfile.TemporaryDirectory() as d:
            cache_path = Path(d) / "cache.json"
            with patch.object(outlook_calendar, "_get_active_outlook",
                              side_effect=outlook_calendar.OutlookNotRunning):
                outlook_calendar._try_sync(cache_path=cache_path, category="Deep Work")

        status = outlook_calendar.last_sync_status()
        self.assertFalse(status["ok"])
        self.assertEqual(status["error"], "Outlook not open")
        # Cache is preserved.
        self.assertEqual(len(outlook_calendar._get_cache_for_tests()["events"]), 1)
        self.assertEqual(outlook_calendar._get_cache_for_tests()["events"][0]["subject"], "Prior")

    def test_arbitrary_com_failure_leaves_cache_unchanged(self):
        prior = {
            "lastSyncAt": "2026-05-09T07:00:00",
            "lastSyncOk": True,
            "lastSyncError": None,
            "events": [{"start": "2026-05-09T09:00:00", "end": "2026-05-09T11:00:00",
                        "subject": "Prior", "isAllDay": False}],
        }
        outlook_calendar._set_cache_for_tests(prior)

        with tempfile.TemporaryDirectory() as d:
            cache_path = Path(d) / "cache.json"
            with patch.object(outlook_calendar, "_get_active_outlook",
                              side_effect=RuntimeError("calendar locked")):
                outlook_calendar._try_sync(cache_path=cache_path, category="Deep Work")

        status = outlook_calendar.last_sync_status()
        self.assertFalse(status["ok"])
        self.assertIn("calendar locked", status["error"])
        self.assertEqual(len(outlook_calendar._get_cache_for_tests()["events"]), 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestTrySync -v`
Expected: FAIL with `AttributeError` for `_try_sync` / `OutlookNotRunning` / `_get_active_outlook` / `last_sync_status` / `_get_cache_for_tests`.

- [ ] **Step 3: Implement orchestration**

Append to `outlook_calendar.py`:
```python
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
    except OSError:
        # Disk write failure is non-fatal — in-memory cache is still updated.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestTrySync -v`
Expected: `Ran 3 tests in 0.0XXs` `OK`.

- [ ] **Step 5: Run the full test file to verify nothing else broke**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar -v`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git -C /Users/simon/repos/app-blocker add outlook_calendar.py tests/test_outlook_calendar.py
git -C /Users/simon/repos/app-blocker commit -m "outlook_calendar: _try_sync orchestration with COM error handling"
```

---

## Task 8: Background sync thread + `force_refresh` + `start_background_sync`

The daemon thread loops every `interval_seconds`, calling `_try_sync`. `force_refresh()` signals it to wake immediately. `start_background_sync()` is idempotent.

**Files:**
- Modify: `tests/test_outlook_calendar.py`
- Modify: `outlook_calendar.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_outlook_calendar.py`:
```python
import time as _time


class TestBackgroundSync(unittest.TestCase):
    def setUp(self):
        outlook_calendar._reset_for_tests()
        # Make sure no thread leaks across tests.
        outlook_calendar._stop_background_sync_for_tests()

    def tearDown(self):
        outlook_calendar._stop_background_sync_for_tests()

    def test_force_refresh_triggers_sync(self):
        call_count = {"n": 0}

        def fake_sync(cache_path, category):
            call_count["n"] += 1

        with patch.object(outlook_calendar, "_try_sync", side_effect=fake_sync):
            with tempfile.TemporaryDirectory() as d:
                cache_path = Path(d) / "cache.json"
                outlook_calendar.start_background_sync(
                    interval_seconds=3600, cache_path=cache_path, category="Deep Work")
                # Initial sync runs once at startup.
                # Wait briefly for the initial pass.
                deadline = _time.time() + 2.0
                while call_count["n"] < 1 and _time.time() < deadline:
                    _time.sleep(0.05)
                self.assertGreaterEqual(call_count["n"], 1)
                # force_refresh triggers another pass.
                outlook_calendar.force_refresh()
                deadline = _time.time() + 2.0
                while call_count["n"] < 2 and _time.time() < deadline:
                    _time.sleep(0.05)
                self.assertGreaterEqual(call_count["n"], 2)

    def test_start_background_sync_is_idempotent(self):
        with patch.object(outlook_calendar, "_try_sync"):
            with tempfile.TemporaryDirectory() as d:
                cache_path = Path(d) / "cache.json"
                outlook_calendar.start_background_sync(
                    interval_seconds=3600, cache_path=cache_path, category="Deep Work")
                outlook_calendar.start_background_sync(
                    interval_seconds=3600, cache_path=cache_path, category="Deep Work")
                # No exception, only one daemon thread.
                self.assertTrue(outlook_calendar._is_background_running_for_tests())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestBackgroundSync -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement the daemon**

Append to `outlook_calendar.py`:
```python
import time as _time


# Sentinel: the daemon thread (or None if not started).
_sync_thread: threading.Thread | None = None
_sync_thread_lock = threading.Lock()
_sync_wakeup = threading.Event()
_sync_stop = threading.Event()


def _sync_loop(cache_path: Path, category: str, interval_seconds: int) -> None:
    """Daemon loop: sync, sleep, repeat. Wakes early if force_refresh fires."""
    while not _sync_stop.is_set():
        try:
            _try_sync(cache_path=cache_path, category=category)
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
            kwargs={"cache_path": cache_path, "category": category,
                    "interval_seconds": interval_seconds},
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar.TestBackgroundSync -v`
Expected: `Ran 2 tests in 0.0XXs` `OK`. (May take up to a couple of seconds because of the wait loops.)

- [ ] **Step 5: Run the full test file**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar -v`
Expected: All tests pass. Total ~25 tests.

- [ ] **Step 6: Commit**

```bash
git -C /Users/simon/repos/app-blocker add outlook_calendar.py tests/test_outlook_calendar.py
git -C /Users/simon/repos/app-blocker commit -m "outlook_calendar: background sync thread, force_refresh, idempotent start"
```

---

## Task 9: Wire `main.py` tick loop and edit-lock to `current_deep_work_event`

Replace the existing `active_window(now, schedule)` calls with `outlook_calendar.current_deep_work_event(now)`. The semantics are identical for the call sites: a non-`None` return means "block now."

**Files:**
- Modify: `main.py`

Quick reference for what to find:

```bash
grep -n "active_window\|schedule" main.py
```

The relevant call sites (line numbers from the current main.py — verify with grep before editing):
- Line ~542: edit-lock check — `window = active_window(now, self._config.get("schedule", {}))`
- Tick loop somewhere in the main blocker class — also calls `active_window`

- [ ] **Step 1: Locate the tick loop and edit-lock callers**

Run:
```bash
grep -n "active_window" /Users/simon/repos/app-blocker/main.py
```

Note every line number that calls `active_window`. The existing function lives at lines 265-276.

- [ ] **Step 2: Add the import at the top of main.py**

Find the existing imports section near the top of `main.py` (~line 13-28). After the `from tkinter import messagebox, ttk` line, add:
```python
import outlook_calendar
```

- [ ] **Step 3: Replace the tick-loop `active_window` call**

In `main.py` around line 542, replace:
```python
            window = active_window(now, self._config.get("schedule", {}))
```
with:
```python
            window = outlook_calendar.current_deep_work_event(now)
```

The variable name `window` is preserved so the rest of the tick block (`if window and blocked_normalized and not break_active:` on line ~551) and the snapshot field (`self._active_window = window` on line ~564) continue to work — they just hold a dict-or-None of a different shape.

- [ ] **Step 4: Fix the two HH:MM consumers in `refresh()`**

The previous `window` shape had `"start"`/`"end"` as `"HH:MM"` strings. The new shape has them as ISO datetime strings (e.g. `"2026-05-09T11:00:00"`). Two places in `refresh()` (around `main.py:1932`) need to be updated.

Around line 1954-1957, replace:
```python
            hero_meta_var.set(
                f"{window.get('start','?')} – {window.get('end','?')} · "
                f"ends at {window.get('end','?')}"
            )
```
with:
```python
            try:
                _w_start = datetime.fromisoformat(window["start"]).strftime("%H:%M")
                _w_end = datetime.fromisoformat(window["end"]).strftime("%H:%M")
                hero_meta_var.set(f"{_w_start} – {_w_end} · ends at {_w_end}")
            except (KeyError, ValueError):
                hero_meta_var.set("Deep work · in progress")
```

Around lines 1958-1968, replace:
```python
            try:
                eh, em = map(int, window["end"].split(":"))
                end_dt = now.replace(
                    hour=eh, minute=em, second=0, microsecond=0,
                )
                if end_dt < now:
                    end_dt += timedelta(days=1)
                rem = (end_dt - now).total_seconds()
                hero_time_var.set(_format_remaining(rem))
            except Exception:
                hero_time_var.set("—")
```
with:
```python
            try:
                end_dt = datetime.fromisoformat(window["end"])
                rem = (end_dt - now).total_seconds()
                hero_time_var.set(_format_remaining(rem) if rem > 0 else "—")
            except Exception:
                hero_time_var.set("—")
```

- [ ] **Step 5: Start the background sync at app launch**

In `main.py`, just before `refresh()` is invoked at the end of `main()` (line ~2126, the line that reads `refresh()` followed by `root.mainloop()`), insert:

```python
    _startup_cfg = killer.snapshot()["config"]
    outlook_calendar.start_background_sync(
        interval_seconds=int(_startup_cfg.get("calendar", {}).get("syncIntervalSeconds", 60)),
        category=str(_startup_cfg.get("calendar", {}).get("deepWorkCategory", "Deep Work")),
    )
```

So the tail of `main()` reads:
```python
    _startup_cfg = killer.snapshot()["config"]
    outlook_calendar.start_background_sync(
        interval_seconds=int(_startup_cfg.get("calendar", {}).get("syncIntervalSeconds", 60)),
        category=str(_startup_cfg.get("calendar", {}).get("deepWorkCategory", "Deep Work")),
    )
    refresh()
    root.mainloop()
```

- [ ] **Step 6: Smoke-run the app on macOS**

Run: `cd /Users/simon/repos/app-blocker && python3 main.py`
Expected on macOS:
- Window opens.
- No crash.
- Calendar module is "disabled" (HAVE_WIN32=False, sys.platform != "win32"); blocker never blocks.
- Today page hero meta should not crash (the new HH:MM-from-ISO parse path runs without throwing). Tab content is unchanged in this task — Calendar UI lands in Task 11.

Close the window when satisfied.

- [ ] **Step 7: Run the unit test suite**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar -v`
Expected: all tests pass (we changed `main.py`, not `outlook_calendar.py`, so the suite should be unaffected).

- [ ] **Step 8: Commit**

```bash
git -C /Users/simon/repos/app-blocker add main.py
git -C /Users/simon/repos/app-blocker commit -m "main: route blocking decision through outlook_calendar.current_deep_work_event"
```

---

## Task 10: Drop `schedule` from DEFAULT_CONFIG; add `calendar` defaults

**Files:**
- Modify: `main.py` (lines ~39-66 — `DEFAULT_CONFIG` block)

- [ ] **Step 1: Edit DEFAULT_CONFIG**

In `main.py`, locate the `DEFAULT_CONFIG: dict = { ... }` block (currently lines ~39-66). Remove the `"schedule": { ... }` entry entirely. Add a new `"calendar"` entry. The block should look like:

```python
DEFAULT_CONFIG: dict = {
    "_README": (
        "Edit this file to customize. Saved changes are picked up within ~1 second. "
        "Blocking is driven by your Outlook calendar: events tagged with the Outlook "
        "Category specified in calendar.deepWorkCategory (default: 'Deep Work') block "
        "for the duration of the event. No event tagged → no block."
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
    },
    "settings": {
        "breakDurationMinutes": 10,
        "cooldownMinutes": 30,
        "challengeWordCount": 50,
    },
}
```

- [ ] **Step 2: Remove `active_window` and `_parse_hhmm`**

Locate the `# Schedule logic` block (around lines 257-276). Delete `_parse_hhmm` and `active_window` — both are now unused (verify with `grep -n "active_window\|_parse_hhmm" main.py` returning no hits before deleting).

- [ ] **Step 3: Smoke-run on macOS**

Run: `cd /Users/simon/repos/app-blocker && python3 main.py`
Expected: window opens, no crash, no references to a missing `schedule` field cause an exception.

- [ ] **Step 4: Commit**

```bash
git -C /Users/simon/repos/app-blocker add main.py
git -C /Users/simon/repos/app-blocker commit -m "main: drop static schedule config; add calendar defaults; remove active_window"
```

---

## Task 11: Replace Schedule UI page with read-only Calendar page

The existing Schedule page is a tabbed UI with an editable list of HH:MM windows per day, plus a `ScheduleWindowEditor` modal. Replace it with a read-only Calendar page showing today's Deep Work events from the cache, sync status, and a "Sync now" button.

**Files:**
- Modify: `main.py`

Approximate current line ranges (verify with grep):
- `class ScheduleWindowEditor` (~lines 969-1085) — DELETE entirely
- `_summarize_schedule_today` (~line 1086) — REPLACE with `_summarize_calendar_today`
- Schedule page rendering (`schedule_page = tk.Frame(...)`, `redraw_schedule_canvas`, `refresh_schedule_tree`, the buttons that call `ScheduleWindowEditor`, etc., ~lines 1446-1700) — REPLACE
- The page registry (`("schedule", "Schedule")`, ~line 1207) — RENAME to `("calendar", "Calendar")`

- [ ] **Step 1: Delete `ScheduleWindowEditor`**

Locate `class ScheduleWindowEditor` and delete the entire class body. Save.

- [ ] **Step 2: Replace `_summarize_schedule_today` with `_summarize_calendar_today`**

Find the existing function:
```python
def _summarize_schedule_today(schedule: dict, now: datetime) -> str:
    day_key = DAY_KEYS[now.weekday()]
    windows = schedule.get(day_key, []) or []
    ...
```

Replace it with:
```python
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
    cache = outlook_calendar._get_cache_for_tests()  # internal read; safe to use read-only
    upcoming = []
    for ev in cache.get("events", []):
        try:
            start = datetime.fromisoformat(ev["start"])
            if start > now:
                upcoming.append((start, ev))
        except (KeyError, ValueError):
            continue
    upcoming.sort(key=lambda pair: pair[0])
    if upcoming:
        return f"Next deep work: {upcoming[0][0].strftime('%H:%M')}"
    return "No deep work blocks today"
```

(Yes, `_get_cache_for_tests` is named "for_tests" but is the only way to read the full event list — the only consequence of using it from `main.py` is a slightly awkward name. Acceptable for now; can rename later.)

- [ ] **Step 3: Update every caller of `_summarize_schedule_today`**

Run:
```bash
grep -n "_summarize_schedule_today" /Users/simon/repos/app-blocker/main.py
```

For each call site, replace:
```python
_summarize_schedule_today(cfg.get("schedule", {}), now)
```
with:
```python
_summarize_calendar_today(now)
```

- [ ] **Step 4: Replace the Schedule page rendering**

Find the block beginning with `# Schedule page` (around line 1446). Replace the entire section (page frame, canvas, treeview, edit/add/delete buttons) with this Calendar page:

```python
    # Calendar page
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
        cache = outlook_calendar._get_cache_for_tests()
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
```

- [ ] **Step 5: Update the page registry**

Find `("schedule", "Schedule")` (~line 1207) and replace with `("calendar", "Calendar")`.

- [ ] **Step 6: Update `refresh()` to use the new Calendar page and remove dead Schedule references**

The existing `refresh()` function (starts at `main.py:1932`) has four blocks tied to the deleted Schedule UI. Apply each:

**6a.** Around line 2067-2068, replace:
```python
        refresh_schedule_tree()
        redraw_schedule_canvas()
```
with:
```python
        refresh_calendar_page()
```

**6b.** Around lines 2070-2083, **delete entirely** the schedule weekly-stats block (it iterates `cfg.get("schedule", ...)` which no longer exists):
```python
        total_min = 0
        for dk in DAY_KEYS:
            for w_ in cfg.get("schedule", {}).get(dk, []):
                try:
                    sh, sm = map(int, w_["start"].split(":"))
                    eh, em = map(int, w_["end"].split(":"))
                    total_min += (eh * 60 + em) - (sh * 60 + sm)
                except Exception:
                    pass
        hours = total_min // 60
        mins = total_min % 60
        sched_stats_var.set(
            f"{hours}h {mins:02d}m blocked per week — repeats every week."
        )
```
(`sched_stats_var` was a Schedule-page widget; it goes away with the page.)

**6c.** Around line 2087-2090, replace the `edit_buttons` tuple to drop the schedule buttons:
```python
        edit_buttons = (
            apps_add_btn, apps_remove_btn,
            sched_add_btn, sched_edit_btn, sched_remove_btn,
        )
```
with:
```python
        edit_buttons = (apps_add_btn, apps_remove_btn)
```

**6d.** Around lines 2095-2097 and 2103-2104 and 2117-2118, **delete every reference to** `sched_lock_banner` and `sched_lock_label` (those widgets are gone). The remaining edit-lock logic for the apps page (`blocks_lock_banner`, `blocks_lock_label`) stays. Specifically:

- Delete `if not sched_lock_banner.winfo_ismapped(): sched_lock_banner.pack(...)` (the 3 lines).
- Delete `if sched_lock_banner.winfo_ismapped(): sched_lock_banner.pack_forget()` (the 2 lines).
- Delete `sched_lock_label.config(text=rem)` and `sched_lock_label.config(text="Schedule frozen during active block.")` (the 2 lines, in their respective branches).

After this step, `grep -n "sched_" main.py` should return zero hits.

- [ ] **Step 7: Smoke-run on macOS**

Run: `cd /Users/simon/repos/app-blocker && python3 main.py`
Expected:
- Window opens.
- "Calendar" tab present where "Schedule" used to be.
- Tab content shows "No Deep Work events today." (cache is empty on macOS dev).
- Sync status reads "Outlook not open" (or similar).
- "Sync now" button is clickable, doesn't crash.
- Today page hero meta reads "No deep work blocks today".

- [ ] **Step 8: Run unit tests**

Run: `cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar -v`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git -C /Users/simon/repos/app-blocker add main.py
git -C /Users/simon/repos/app-blocker commit -m "main: replace Schedule UI with read-only Calendar page"
```

---

## Task 12: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add pywin32 requirement**

Open `README.md`. Find the section that begins:
```
Requires Python 3.9+ and Git on PATH. No Python dependencies needed.
```
Replace with:
```
Requires Python 3.9+ and Git on PATH.

**On Windows (deploy target):** also install pywin32 — `pip install --user pywin32`. Required for the Outlook calendar integration.

**On macOS (dev only):** no extra dependencies; calendar integration is disabled and the blocker is inactive.
```

- [ ] **Step 2: Mention the calendar in the project description**

In the "Optional speedup" section (psutil), the README is silent about how blocking decisions work. Add a brief explanation just above "Optional speedup":

```
## How blocking is scheduled

The blocker reads your Outlook calendar (via local COM, no network). Any event tagged with the Outlook Category "Deep Work" causes the configured apps to be killed for the duration of the event. Untag an event or end it early to lift the block immediately.

You must have Outlook open at least once after the app starts so the calendar can sync; the cache then survives Outlook being killed during a Deep Work block.
```

- [ ] **Step 3: Commit**

```bash
git -C /Users/simon/repos/app-blocker add README.md
git -C /Users/simon/repos/app-blocker commit -m "README: document pywin32 requirement and calendar behavior"
```

---

## Task 13: Manual integration test on Windows

This task does not produce a commit — it verifies the end-to-end flow on the work laptop.

**Files:** none (verification only)

Per the spec's "Integration test (Windows, manual)" section:

- [ ] **Step 1: Pull on the work laptop and start the app**

```
cd /d "%USERPROFILE%\app-blocker"
git pull
python main.py
```

Verify:
- Window opens, no Python traceback.
- Calendar tab shows "Outlook not open" until you open Outlook.

- [ ] **Step 2: Open Outlook, wait up to 60s, confirm sync**

Open Outlook. Wait 60s (or click "Sync now"). Verify:
- Calendar tab status changes to "Last synced at <iso>".
- If you have any "Deep Work"-tagged events today, they're listed.

- [ ] **Step 3: Future-event test**

In Outlook, create a calendar event:
- Subject: `Test focus block`
- Start: 2 minutes from now
- End: 5 minutes from now
- Categories: `Deep Work`

Save it. Wait for the 2-minute mark. Verify within 60s of start time:
- Today page hero shows "Deep work · ends HH:MM".
- Configured blocked apps (Notepad/Calculator demo) are killed if running.

- [ ] **Step 4: Outlook-killed-mid-block test**

While the block is active, kill Outlook (close it, or use Task Manager). Wait. Verify:
- Block continues — apps stay killed.
- Calendar tab status now reads "Outlook not open" but the events list still shows the block.

- [ ] **Step 5: Block-end test**

Wait for the event end time. Verify within 60s of end time:
- Block lifts; apps can be relaunched.
- Today page hero returns to "No deep work blocks today" (or "Next: ...").

- [ ] **Step 6: Document any deviations**

If anything diverges from expected behavior, note it in this checklist (or open an issue) before moving on. The most likely failure mode is the Restrict date format — `_fetch_today_events_from_outlook` uses `%m/%d/%Y` which is en-US. If the work laptop's locale is different, items.Restrict will silently match nothing — you'd see no events even when Deep Work events exist.

If Restrict format is the issue: log `restricted.GetFirst()` and the restrict string from `_fetch_today_events_from_outlook` to find the locale-correct format, then fix in code and commit a follow-up.

---

## Task 14: Cleanup — remove the temporary reference

**Files:**
- Delete: `gencache_example.py`

- [ ] **Step 1: Delete the temp file**

Run:
```bash
rm /Users/simon/repos/app-blocker/gencache_example.py
```

`gencache_example.py` is untracked, so no commit is required. Verify:
```bash
git -C /Users/simon/repos/app-blocker status
```
Should report a clean working tree.

- [ ] **Step 2: Final verification — run the test suite one more time**

Run:
```bash
cd /Users/simon/repos/app-blocker && python3 -m unittest tests.test_outlook_calendar -v
```
Expected: all tests pass.

- [ ] **Step 3: Final verification — smoke-run the app**

Run:
```bash
cd /Users/simon/repos/app-blocker && python3 main.py
```
Expected: window opens, Calendar tab present, no crashes.

---

## Spec coverage check

Each requirement from the spec maps to a task:

| Spec requirement | Task |
|---|---|
| Drop static `schedule`; calendar replaces it | 9, 10 |
| `outlook_calendar.py` public API | 5, 7, 8 |
| `GetActiveObject` (never `Dispatch`) | 7 |
| Cache shape on disk + in memory | 4, 7 |
| 60s background daemon | 8 |
| Tick uses `current_deep_work_event` | 9 |
| Pure helpers unit-tested | 2, 3, 4, 5 |
| COM fetch with mocked tests | 6 |
| Outlook-not-running fallback | 7 |
| Calendar UI page replaces Schedule UI | 11 |
| Today-page hero meta | 11 |
| `pywin32` requirement documented | 12 |
| Manual integration test | 13 |
| Reference notes (EnsureDispatch → GetActiveObject, Restrict, Categories) | 6, 7 |
| Cleanup of temp reference | 14 |
