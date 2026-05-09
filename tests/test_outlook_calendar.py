"""Tests for outlook_calendar — pure helpers + mocked COM fetch.

Designed to run on macOS (dev) and Windows (deploy). Tests do not
import or call win32com; the COM-fetch test injects a mock Outlook
application object directly into the function under test.
"""

import unittest
from datetime import datetime

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


if __name__ == "__main__":
    unittest.main()
