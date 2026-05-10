# `main.py` Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose the 1,993-line `main.py` into focused modules, add unit tests for the pure helpers, and split the 940-line `main()` body into a `MainWindow` class — without changing any runtime behavior.

**Architecture:** Flat modules at the repo root, alongside the existing `tray.py` and `outlook_calendar.py` (so the deployment story — `python main.py` from a fresh `git clone` — does not change). Three phases, in user-requested order: (1) file split, (3) unit tests for pure helpers, (2) `MainWindow` class. Phase 2's tests act as a regression net for phase 3.

**Tech stack:** Python 3.9+, tkinter, `unittest` (pytest as runner). No new dependencies.

---

## Module layout (target)

```
app-blocker/
  main.py            # entry point + MainWindow class only
  style.py           # palette + font cache + F() helper
  paths.py           # app_data_dir, config_path, state_path, words_path,
                     # DEFAULT_CONFIG, DEFAULT_STATE, EDIT_UNLOCK_MINUTES,
                     # load_or_create_config, save_config, load_state, save_state
  wordlist.py        # _FALLBACK_WORDS, load_wordlist
  processes.py       # list_processes, kill_pid, _normalize,
                     # collect_blocked_normalized, CREATE_NO_WINDOW
  killer.py          # KillerThread, _parse_iso, _pick_latest_window, TICK_INTERVAL
  challenge.py       # ChallengeModal
  app_picker.py      # AppPicker
  autostart.py       # is/install/uninstall_launch_at_login + LAUNCH_LABEL
  summaries.py       # _summarize_blocked, _summarize_calendar_today, _format_remaining
  outlook_calendar.py  # (unchanged)
  tray.py              # (unchanged)
```

Import dependency graph (no cycles):

```
main → style, paths, wordlist, processes, killer, challenge, app_picker,
       autostart, summaries, outlook_calendar, tray
killer → paths, processes, outlook_calendar
challenge → style
app_picker → processes
summaries → outlook_calendar
style, paths, wordlist, processes, autostart → (stdlib only)
```

---

## Phase 1: File split

Goal: identical behavior, smaller files. Each task moves one banner-delimited section into its own module and deletes it from `main.py`. After each task, run `pytest` to confirm the existing 46 tests still pass, and `python3 -c "import main"` to confirm the import graph still resolves.

Note: the existing test `tests/test_main_calendar.py` imports `main._summarize_calendar_today`. That import is updated in Task 1.9 (when `_summarize_calendar_today` moves).

### Task 1.1: Extract `style.py`

**Files:**
- Create: `style.py`
- Modify: `main.py` — remove lines 76–122 (visual-style banner block), add `from style import *` near the existing imports

- [ ] **Step 1: Create `style.py`** with the contents of `main.py:76–122` verbatim — palette constants (`PAPER`, `PAPER_ALT`, `WHITE`, `INK`, `INK2`, `INK3`, `LINE`, `ACCENT`, `ACCENT_SOFT`, `OK_GREEN`, `WARN`), `_FONT_CACHE`, `_pick_family`, `init_fonts`, `F`. Add `import tkinter as tk` and `from __future__ import annotations` at the top.

- [ ] **Step 2: Update `main.py`** — replace the deleted block with `from style import (PAPER, PAPER_ALT, WHITE, INK, INK2, INK3, LINE, ACCENT, ACCENT_SOFT, OK_GREEN, WARN, _FONT_CACHE, init_fonts, F)`.

- [ ] **Step 3: Run tests**

```
python3 -m pytest tests/ -q
```
Expected: all 46 pass.

- [ ] **Step 4: Smoke import**

```
python3 -c "import main; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```
git add style.py main.py
git commit -m "refactor: extract visual style + fonts into style.py"
```

### Task 1.2: Extract `paths.py`

**Files:**
- Create: `paths.py`
- Modify: `main.py` — remove `DEFAULT_CONFIG`, `DEFAULT_STATE`, `EDIT_UNLOCK_MINUTES` (33–73) and the paths/IO block (124–176)

- [ ] **Step 1: Create `paths.py`** with `from __future__ import annotations`, `import json`, `from pathlib import Path`, then verbatim:
  - `DEFAULT_CONFIG`, `DEFAULT_STATE`, `EDIT_UNLOCK_MINUTES`
  - `app_data_dir`, `config_path`, `state_path`, `words_path`
  - `load_or_create_config`, `save_config`, `load_state`, `save_state`

- [ ] **Step 2: Update `main.py`** — replace the two deleted blocks with `from paths import (DEFAULT_CONFIG, DEFAULT_STATE, EDIT_UNLOCK_MINUTES, app_data_dir, config_path, state_path, words_path, load_or_create_config, save_config, load_state, save_state)`.

- [ ] **Step 3: Run tests + smoke import** (same commands as Task 1.1).

- [ ] **Step 4: Commit**

```
git add paths.py main.py
git commit -m "refactor: extract paths + config/state IO into paths.py"
```

### Task 1.3: Extract `wordlist.py`

**Files:**
- Create: `wordlist.py`
- Modify: `main.py` — remove the `_FALLBACK_WORDS` literal + `load_wordlist` (178–252)

- [ ] **Step 1: Create `wordlist.py`** with `from __future__ import annotations`, `from pathlib import Path`, then `_FALLBACK_WORDS` and `load_wordlist` verbatim.

- [ ] **Step 2: Update `main.py`** — `from wordlist import load_wordlist`.

- [ ] **Step 3: Run tests + smoke import.**

- [ ] **Step 4: Commit**

```
git add wordlist.py main.py
git commit -m "refactor: extract wordlist loader + fallback into wordlist.py"
```

### Task 1.4: Extract `processes.py`

**Files:**
- Create: `processes.py`
- Modify: `main.py` — remove the process enum/kill block (255–356) and the `CREATE_NO_WINDOW` constant on line 34

- [ ] **Step 1: Create `processes.py`** with imports (`os`, `signal`, `subprocess`, `sys`), `CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)`, then verbatim:
  - `_normalize`, `collect_blocked_normalized`
  - `list_processes`, `_list_windows_tasklist`, `_list_unix_ps`, `kill_pid`

- [ ] **Step 2: Update `main.py`** — `from processes import (list_processes, kill_pid, _normalize, collect_blocked_normalized, CREATE_NO_WINDOW)` (some may be unused once `killer.py` is extracted; leave them imported until then so we don't break each step in isolation).

- [ ] **Step 3: Run tests + smoke import.**

- [ ] **Step 4: Commit**

```
git add processes.py main.py
git commit -m "refactor: extract process enumeration + kill into processes.py"
```

### Task 1.5: Extract `killer.py`

**Files:**
- Create: `killer.py`
- Modify: `main.py` — remove `TICK_INTERVAL` constant (33), `_parse_iso`, `_pick_latest_window`, and `class KillerThread` (359–614)

- [ ] **Step 1: Create `killer.py`** with imports (`json`, `threading`, `time`, `datetime`, `timedelta`), `import outlook_calendar`, `from paths import config_path, load_or_create_config, load_state, save_state`, `from processes import collect_blocked_normalized, kill_pid, list_processes, _normalize`. Then `TICK_INTERVAL = 1.0` and verbatim: `_parse_iso`, `_pick_latest_window`, `KillerThread`.

- [ ] **Step 2: Update `main.py`** — `from killer import KillerThread` (TICK_INTERVAL is no longer needed in main.py).

- [ ] **Step 3: Run tests + smoke import.**

- [ ] **Step 4: Commit**

```
git add killer.py main.py
git commit -m "refactor: extract KillerThread + datetime helpers into killer.py"
```

### Task 1.6: Extract `challenge.py`

**Files:**
- Create: `challenge.py`
- Modify: `main.py` — remove `class ChallengeModal` (617–820)

- [ ] **Step 1: Create `challenge.py`** with `from __future__ import annotations`, `import tkinter as tk`, `from style import (PAPER, PAPER_ALT, WHITE, INK, INK2, INK3, LINE, ACCENT, WARN, _FONT_CACHE, F)`. Then `ChallengeModal` verbatim.

- [ ] **Step 2: Update `main.py`** — `from challenge import ChallengeModal`.

- [ ] **Step 3: Run tests + smoke import.**

- [ ] **Step 4: Commit**

```
git add challenge.py main.py
git commit -m "refactor: extract ChallengeModal into challenge.py"
```

### Task 1.7: Extract `app_picker.py`

**Files:**
- Create: `app_picker.py`
- Modify: `main.py` — remove `class AppPicker` (823–908)

- [ ] **Step 1: Create `app_picker.py`** with `from __future__ import annotations`, `import tkinter as tk`, `from tkinter import ttk`, `from processes import list_processes`. Then `AppPicker` verbatim.

- [ ] **Step 2: Update `main.py`** — `from app_picker import AppPicker`.

- [ ] **Step 3: Run tests + smoke import.**

- [ ] **Step 4: Commit**

```
git add app_picker.py main.py
git commit -m "refactor: extract AppPicker modal into app_picker.py"
```

### Task 1.8: Extract `autostart.py`

**Files:**
- Create: `autostart.py`
- Modify: `main.py` — remove `LAUNCH_LABEL` and the launch-at-login block (911–1002)

- [ ] **Step 1: Create `autostart.py`** with imports (`os`, `subprocess`, `sys`, `Path`), `LAUNCH_LABEL = "com.simon.appblocker"`, then verbatim: `_macos_plist_path`, `_windows_startup_path`, `is_launch_at_login_installed`, `install_launch_at_login`, `uninstall_launch_at_login`.

- [ ] **Step 2: Update `main.py`** — `from autostart import (is_launch_at_login_installed, install_launch_at_login, uninstall_launch_at_login)`.

- [ ] **Step 3: Run tests + smoke import.**

- [ ] **Step 4: Commit**

```
git add autostart.py main.py
git commit -m "refactor: extract launch-at-login into autostart.py"
```

### Task 1.9: Extract `summaries.py`

**Files:**
- Create: `summaries.py`
- Modify: `main.py` — remove `_summarize_blocked`, `_summarize_calendar_today`, `_format_remaining` (1010–1051)
- Modify: `tests/test_main_calendar.py` — change `import main` / `main._summarize_calendar_today` to `import summaries` / `summaries._summarize_calendar_today`

- [ ] **Step 1: Create `summaries.py`** with `from __future__ import annotations`, `from datetime import datetime`, `import outlook_calendar`. Then `_summarize_blocked`, `_summarize_calendar_today`, `_format_remaining` verbatim.

- [ ] **Step 2: Update `main.py`** — `from summaries import (_summarize_blocked, _summarize_calendar_today, _format_remaining)`.

- [ ] **Step 3: Update `tests/test_main_calendar.py`** — replace `import main` with `import summaries` and `main._summarize_calendar_today(...)` with `summaries._summarize_calendar_today(...)`. The module-level docstring's reference to `main.py` should be updated to `summaries.py` to avoid stale comments.

- [ ] **Step 4: Run tests + smoke import.** All 46 should still pass; one moved file should still pass.

- [ ] **Step 5: Commit**

```
git add summaries.py main.py tests/test_main_calendar.py
git commit -m "refactor: extract summary helpers into summaries.py; update tests"
```

### Task 1.10: Phase 1 verification

- [ ] **Step 1: Confirm `main.py` is now a thin entry point + UI.**

```
wc -l main.py style.py paths.py wordlist.py processes.py killer.py \
       challenge.py app_picker.py autostart.py summaries.py
```
Expected: `main.py` is roughly 1,000 lines (the UI + main()), each new module is well under 300 lines.

- [ ] **Step 2: Launch the UI on macOS** (dev box) to confirm the window opens and tabs switch:

```
python3 main.py &
sleep 2
# Open the window manually, click each nav tab (Today / Calendar / Block lists / Settings)
# Confirm no tracebacks. Then close.
```
Expected: identical UI to before.

- [ ] **Step 3: No commit needed for verification** — phase complete.

---

## Phase 2 (executed second): Unit tests for pure helpers

Goal: regression net before we touch `main()`. Each test file is independent. The functions we are testing are *prefixed with underscore* (private) but already used cross-module — testing them is fair game and aligns with how `tests/test_main_calendar.py` already tests `_summarize_calendar_today`.

### Task 2.1: Tests for `_normalize` and `collect_blocked_normalized`

**Files:**
- Create: `tests/test_processes_helpers.py`

- [ ] **Step 1: Write the test file**

```python
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
```

- [ ] **Step 2: Run the new tests**

```
python3 -m pytest tests/test_processes_helpers.py -v
```
Expected: all pass (these helpers are already correct in production code).

- [ ] **Step 3: Run the full suite**

```
python3 -m pytest tests/ -q
```
Expected: 46 + 9 = 55 passing.

- [ ] **Step 4: Commit**

```
git add tests/test_processes_helpers.py
git commit -m "test: add unit tests for _normalize / collect_blocked_normalized"
```

### Task 2.2: Tests for `_parse_iso` and `_pick_latest_window`

**Files:**
- Create: `tests/test_killer_helpers.py`

- [ ] **Step 1: Write the test file**

```python
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
```

- [ ] **Step 2: Run the new tests + full suite.** Expected: all pass.

- [ ] **Step 3: Commit**

```
git add tests/test_killer_helpers.py
git commit -m "test: add unit tests for _parse_iso / _pick_latest_window"
```

### Task 2.3: Tests for `_summarize_blocked` and `_format_remaining`

**Files:**
- Modify: `tests/test_main_calendar.py` — rename to `tests/test_summaries.py` (more accurate after the file split) and add cases. Or just append.

Decision: append to `tests/test_main_calendar.py` (file already exists and tests `summaries`); rename in same task for consistency with the new module name.

- [ ] **Step 1: Rename the test file**

```
git mv tests/test_main_calendar.py tests/test_summaries.py
```

- [ ] **Step 2: Append two test classes to `tests/test_summaries.py`** (after `TestSummarizeCalendarToday`):

```python
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
```

- [ ] **Step 3: Run the full suite.** Expected: all pass (a `git mv` does not break test discovery; pytest finds the new path).

- [ ] **Step 4: Commit**

```
git add tests/test_summaries.py
git commit -m "test: cover _summarize_blocked + _format_remaining; rename to test_summaries.py"
```

---

## Phase 3 (executed third): Decompose `main()` into `MainWindow`

Goal: replace the procedural ~940-line `main()` with a `MainWindow` class whose `__init__` builds the UI from focused `_build_*` methods. Closures become methods. The widget references that closures captured become `self.<attr>` so methods can reach them.

Strategy: do this in *one* commit, not page-by-page, because the closures are tightly interleaved (one closure references widgets created hundreds of lines later, etc.). Splitting into smaller commits would either temporarily break the file or require shim functions. Instead, do it all at once and rely on the test suite + a manual UI smoke check for verification.

### Task 3.1: Convert `main()` to `MainWindow` class

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Sketch the target shape**

```python
class MainWindow:
    def __init__(self) -> None:
        load_or_create_config()
        self.wordlist, self.wordlist_source = load_wordlist()
        self.killer = KillerThread()
        self.killer.start()
        self.started_at = time.monotonic()

        self.root = tk.Tk()
        self._setup_root()
        self._setup_styles()
        self._setup_tray()
        self._build_shell()
        self._build_sidebar()
        self._build_today_page()
        self._build_calendar_page()
        self._build_blocks_page()
        self._build_settings_page()
        self._set_page("today")
        self._start_calendar_sync()
        self._refresh()

    def run(self) -> None:
        self.root.mainloop()

    # --- builders ---
    def _setup_root(self): ...
    def _setup_styles(self): ...
    def _setup_tray(self): ...
    def _build_shell(self): ...
    def _build_sidebar(self): ...
    def _build_today_page(self): ...
    def _build_calendar_page(self): ...
    def _build_blocks_page(self): ...
    def _build_settings_page(self): ...

    # --- behavior ---
    def _set_page(self, key): ...
    def _update_nav_visual(self): ...
    def _restore_window(self): ...
    def _quit_app(self): ...
    def _on_close(self): ...
    def _on_unmap(self, event): ...
    def _make_button(self, parent, text, command): ...
    def _set_button_enabled(self, btn, enabled): ...
    def _challenge_word_count(self): ...
    def _open_challenge(self): ...
    def _open_edit_unlock_challenge(self): ...
    def _start_focus(self, minutes): ...
    def _reset_state(self): ...
    def _refresh(self): ...
    def _refresh_apps_list(self): ...
    def _refresh_calendar_page(self): ...
    def _add_app_via_picker(self): ...
    def _remove_selected_app(self): ...
    def _toggle_launch_at_login(self): ...
    def _write_settings_from_vars(self): ...
    def _load_settings_from_config(self, cfg): ...


def main() -> None:
    MainWindow().run()
```

- [ ] **Step 2: Mechanical conversion**
  - Move every local variable in `main()` that survives across closures (`root`, `tray_icon`, `killer`, `wordlist`, `started_at`, all `*_var` StringVars/IntVars/BooleanVars, page frames, button refs, `pages`, `nav_widgets`, `current_page`, `displayed_app_ids`, `spinboxes`, `settings_loading`, `cal_inner`, `cal_list_frame`, `cal_status_var`, `apps_listbox`, etc.) to `self.<name>`.
  - Move every nested `def` to a method on `MainWindow`. Lambdas that capture state get rewritten to `self.<method>` calls or `lambda: self._foo()`.
  - Constants used only by the UI (palette, fonts) keep their imported names — they don't need to become attributes.
  - Place `_build_*` methods in the same source order as they were declared procedurally — easier to diff.
  - At the bottom, `main()` becomes:

```python
def main() -> None:
    MainWindow().run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the test suite**

```
python3 -m pytest tests/ -q
```
Expected: all 60+ tests pass (KillerThread + summaries don't depend on the UI, so they should be unaffected).

- [ ] **Step 4: Smoke-launch the UI on macOS**

```
python3 main.py
```
Visually verify:
  - Window opens with sidebar (Today / Calendar / Block lists / Settings)
  - Each nav tab switches the content area
  - Today page shows hero card + three stat tiles + buttons
  - Settings page shows three spinboxes + "Launch at login" checkbox
  - Closing the window exits cleanly (no hung KillerThread keeping the process alive — `Ctrl+C` if needed; on Mac the `tray` integration is a no-op so the close path goes via `_quit_app`)

- [ ] **Step 5: Commit**

```
git add main.py
git commit -m "refactor: split main() into MainWindow class + builder methods"
```

### Task 3.2: Phase 3 verification

- [ ] **Step 1: Confirm overall stats**

```
wc -l main.py
```
Expected: roughly 1,000 → 1,100 lines, dominated by the `MainWindow` class. Every method should be under ~80 lines.

- [ ] **Step 2: Confirm `main.py` no longer contains nested `def`s inside another function** (a quick proxy for "no more massive closures"):

```
grep -n "^    def " main.py | head
grep -n "^        def " main.py
```
Expected: top-level `def main`, plus indented method defs at depth 4 (class methods). No depth-8 nested defs.

- [ ] **Step 3: Hand-off** to user for final end-to-end check on the Windows deploy box (per the user's stated workflow: they verify at the end). If anything is broken, return to the failing task. No commit needed.

---

## Self-review checklist

- **Spec coverage:** Each of the user's three asks (file split, decompose `main()`, tests for pure helpers) maps to a phase. Order matches user request: 1 → 3 → 2.
- **Placeholder scan:** No "TBD" / "fill in" / "similar to above". Every test file shows full code; every module extraction shows the precise line range and updated import statement.
- **Type/name consistency:** `_summarize_calendar_today`, `_format_remaining`, `_summarize_blocked`, `_normalize`, `collect_blocked_normalized`, `_parse_iso`, `_pick_latest_window`, `KillerThread`, `ChallengeModal`, `AppPicker`, `is_launch_at_login_installed`, `install_launch_at_login`, `uninstall_launch_at_login` — names match the source file and are used consistently across phases.
- **Risk:** the only place behavior could drift is Phase 3 Task 3.1 (the `main()` rewrite). Phase 2's regression tests cover the pure helpers; the UI itself is verified by manual smoke. If 3.1 misbehaves in a way the tests don't catch, `git revert` is the quick exit.
