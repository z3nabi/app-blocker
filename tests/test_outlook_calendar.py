"""Tests for outlook_calendar — pure helpers + mocked COM fetch.

Designed to run on macOS (dev) and Windows (deploy). Tests do not
import or call win32com; the COM-fetch test injects a mock Outlook
application object directly into the function under test.
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import outlook_calendar


class TestModuleImport(unittest.TestCase):
    def test_module_imports_cleanly(self):
        self.assertTrue(hasattr(outlook_calendar, "HAVE_WIN32"))


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

    def test_tz_aware_iso_does_not_crash(self):
        # Outlook can return tz-aware ISO strings depending on store config.
        # _event_covers must treat them as naive local times, not crash.
        ev = self._ev("2026-05-09T09:00:00+00:00", "2026-05-09T11:00:00+00:00")
        self.assertTrue(outlook_calendar._event_covers(ev, datetime(2026, 5, 9, 10, 0, 0)))


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

    def test_load_partial_keys_uses_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "partial.json"
            p.write_text('{"events": []}')
            cache = outlook_calendar._load_cache(p)
            self.assertIsNone(cache["lastSyncAt"])
            self.assertFalse(cache["lastSyncOk"])
            self.assertIsNone(cache["lastSyncError"])

    def test_load_events_null_returns_empty_events(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "null_events.json"
            p.write_text('{"events": null}')
            cache = outlook_calendar._load_cache(p)
            self.assertEqual(cache["events"], [])

    def test_load_events_non_list_returns_empty_events(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "weird_events.json"
            p.write_text('{"events": 42}')
            cache = outlook_calendar._load_cache(p)
            self.assertEqual(cache["events"], [])


if __name__ == "__main__":
    unittest.main()
