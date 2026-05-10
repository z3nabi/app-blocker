"""Tests for the calendar-summary helpers in summaries.py.

Specifically: `_summarize_calendar_today` must tolerate timezone-aware
ISO strings in the cache. pywintypes emits tz-aware datetimes for Outlook
event Start/End, so the on-disk cache regularly contains strings like
"2026-05-09T15:00:00+02:00". The summary function compares these against
`datetime.now()` (tz-naive), so it must strip tzinfo defensively — same
pattern as `outlook_calendar._event_covers`.
"""

import os
import unittest
from datetime import datetime

# Silence module trace output BEFORE importing outlook_calendar / summaries.
os.environ["OUTLOOK_CALENDAR_TRACE"] = "0"

import outlook_calendar  # noqa: E402
import summaries  # noqa: E402

outlook_calendar._TRACE_ENABLED = False


class TestSummarizeCalendarToday(unittest.TestCase):
    def setUp(self):
        outlook_calendar._reset_for_tests()

    def tearDown(self):
        outlook_calendar._reset_for_tests()

    def test_upcoming_block_with_tz_aware_cached_event(self):
        outlook_calendar._set_cache_for_tests({
            "events": [{
                "start": "2026-05-09T15:00:00+02:00",
                "end":   "2026-05-09T16:00:00+02:00",
                "subject": "Deep Work",
                "isAllDay": False,
            }],
        })
        naive_now = datetime(2026, 5, 9, 10, 0, 0)
        result = summaries._summarize_calendar_today(naive_now)
        self.assertIn("15:00", result)

    def test_current_block_with_tz_aware_cached_event(self):
        outlook_calendar._set_cache_for_tests({
            "events": [{
                "start": "2026-05-09T09:00:00+02:00",
                "end":   "2026-05-09T11:00:00+02:00",
                "subject": "Deep Work",
                "isAllDay": False,
            }],
        })
        naive_now = datetime(2026, 5, 9, 10, 0, 0)
        result = summaries._summarize_calendar_today(naive_now)
        self.assertIn("11:00", result)

    def test_no_blocks_today_returns_placeholder(self):
        outlook_calendar._set_cache_for_tests({"events": []})
        naive_now = datetime(2026, 5, 9, 10, 0, 0)
        self.assertEqual(
            summaries._summarize_calendar_today(naive_now),
            "No deep work blocks today",
        )


class TestSummarizeBlocked(unittest.TestCase):
    def test_with_apps(self):
        cfg = {
            "blockedApps": [
                {"matchers": {"names": ["Notepad", "Notepad.exe"]}},
                {"matchers": {"names": ["Calculator"]}},
            ]
        }
        self.assertEqual(
            summaries._summarize_blocked(cfg),
            "Notepad, Notepad.exe, Calculator",
        )

    def test_empty(self):
        self.assertEqual(
            summaries._summarize_blocked({"blockedApps": []}),
            "(no apps configured)",
        )

    def test_missing_key(self):
        self.assertEqual(
            summaries._summarize_blocked({}),
            "(no apps configured)",
        )

    def test_apps_without_names(self):
        cfg = {"blockedApps": [{"matchers": {}}]}
        self.assertEqual(
            summaries._summarize_blocked(cfg),
            "(no matchers)",
        )


class TestFormatRemaining(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(summaries._format_remaining(0), "0:00")

    def test_negative(self):
        self.assertEqual(summaries._format_remaining(-5), "0:00")

    def test_seconds_only(self):
        self.assertEqual(summaries._format_remaining(45), "0:45")

    def test_one_minute(self):
        self.assertEqual(summaries._format_remaining(60), "1:00")

    def test_minutes_and_seconds(self):
        self.assertEqual(summaries._format_remaining(125), "2:05")

    def test_pads_seconds(self):
        self.assertEqual(summaries._format_remaining(3601), "60:01")


if __name__ == "__main__":
    unittest.main()
