"""Tests for the pure name-matching helpers in processes.py."""

import unittest

from processes import _normalize, collect_blocked_normalized


class TestNormalize(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(_normalize("NotePad"), "notepad")

    def test_strips_exe_suffix(self):
        self.assertEqual(_normalize("Notepad.exe"), "notepad")

    def test_strips_whitespace(self):
        self.assertEqual(_normalize("  Notepad.exe  "), "notepad")

    def test_only_strips_trailing_exe(self):
        self.assertEqual(_normalize("exec.bin"), "exec.bin")

    def test_empty_string(self):
        self.assertEqual(_normalize(""), "")


class TestCollectBlockedNormalized(unittest.TestCase):
    def test_collects_across_apps(self):
        apps = [
            {"matchers": {"names": ["Notepad", "Notepad.exe"]}},
            {"matchers": {"names": ["Calculator"]}},
        ]
        self.assertEqual(
            collect_blocked_normalized(apps),
            {"notepad", "calculator"},
        )

    def test_handles_app_without_matchers(self):
        self.assertEqual(collect_blocked_normalized([{}]), set())

    def test_handles_app_without_names(self):
        self.assertEqual(
            collect_blocked_normalized([{"matchers": {}}]), set()
        )

    def test_empty_input(self):
        self.assertEqual(collect_blocked_normalized([]), set())


if __name__ == "__main__":
    unittest.main()
