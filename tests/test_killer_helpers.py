"""Tests for the pure datetime helpers in killer.py."""

import os
import unittest
from datetime import datetime

# Match the existing convention in test_main_calendar.py — silence trace
# output before importing modules that trigger outlook_calendar import.
os.environ["OUTLOOK_CALENDAR_TRACE"] = "0"

from killer import _parse_iso, _pick_latest_window  # noqa: E402


class TestParseIso(unittest.TestCase):
    def test_parses_naive(self):
        self.assertEqual(
            _parse_iso("2026-05-09T15:00:00"),
            datetime(2026, 5, 9, 15, 0, 0),
        )

    def test_parses_tz_aware(self):
        result = _parse_iso("2026-05-09T15:00:00+02:00")
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.hour, 15)
        self.assertIsNotNone(result.tzinfo)

    def test_returns_none_for_none(self):
        self.assertIsNone(_parse_iso(None))

    def test_returns_none_for_empty(self):
        self.assertIsNone(_parse_iso(""))

    def test_returns_none_for_garbage(self):
        self.assertIsNone(_parse_iso("not a date"))


class TestPickLatestWindow(unittest.TestCase):
    def _w(self, end):
        return {"start": "2026-05-09T09:00:00", "end": end, "subject": "x"}

    def test_picks_later_end(self):
        a = self._w("2026-05-09T10:00:00")
        b = self._w("2026-05-09T11:00:00")
        self.assertEqual(_pick_latest_window(a, b), b)

    def test_picks_a_when_b_is_none(self):
        a = self._w("2026-05-09T10:00:00")
        self.assertEqual(_pick_latest_window(a, None), a)

    def test_picks_b_when_a_is_none(self):
        b = self._w("2026-05-09T10:00:00")
        self.assertEqual(_pick_latest_window(None, b), b)

    def test_returns_none_when_both_none(self):
        self.assertIsNone(_pick_latest_window(None, None))

    def test_falls_back_to_b_if_a_end_unparseable(self):
        a = {"end": "garbage"}
        b = self._w("2026-05-09T10:00:00")
        self.assertEqual(_pick_latest_window(a, b), b)

    def test_falls_back_to_a_if_b_end_unparseable(self):
        a = self._w("2026-05-09T10:00:00")
        b = {"end": "garbage"}
        self.assertEqual(_pick_latest_window(a, b), a)


if __name__ == "__main__":
    unittest.main()
