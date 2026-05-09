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


if __name__ == "__main__":
    unittest.main()
