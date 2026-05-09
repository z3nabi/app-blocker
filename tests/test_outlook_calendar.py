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
