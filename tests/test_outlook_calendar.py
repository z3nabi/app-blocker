"""Tests for outlook_calendar — pure helpers + mocked COM fetch.

Designed to run on macOS (dev) and Windows (deploy). Tests do not
import or call win32com; the COM-fetch test injects a mock Outlook
application object directly into the function under test.
"""

import json
import tempfile
import unittest
from datetime import datetime, date
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
        # Verify presence AND order via mock_calls.
        items_collection = outlook.GetNamespace.return_value.GetDefaultFolder.return_value.Items
        items_collection.Sort.assert_called_once_with("[Start]")
        self.assertEqual(items_collection.IncludeRecurrences, True)
        items_collection.Restrict.assert_called_once()

        # Order check: walk mock_calls and find the indices.
        names_in_order = [c[0] for c in items_collection.mock_calls]
        # mock_calls records attribute reads/sets too; we look for the three operations.
        # Sort and Restrict appear by method name; setting IncludeRecurrences appears
        # under the empty-string method (a property-set marker varies by mock version).
        # The robust check: verify Sort comes before Restrict.
        sort_idx = names_in_order.index("Sort")
        restrict_idx = names_in_order.index("Restrict")
        self.assertLess(sort_idx, restrict_idx,
                        f"Sort must be called before Restrict; got order: {names_in_order}")

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


if __name__ == "__main__":
    unittest.main()
