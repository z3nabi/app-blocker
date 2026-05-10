"""Paths, defaults, and config/state file IO for the app-blocker."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_CONFIG: dict = {
    "_README": (
        "Edit this file to customize. Saved changes are picked up within ~1 second. "
        "Blocking is driven by your Outlook calendar: events tagged with the Outlook "
        "Category specified in calendar.deepWorkCategory (default: 'Deep Work') block "
        "for the duration of the event. No event tagged → no block. "
        "Add names to calendar.additionalCalendars to also scan secondary Outlook "
        "calendars (e.g. ['Work Blocks'])."
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
        # Names of secondary Outlook calendars to also scan (in addition to the
        # default). Use the exact display name as it appears in Outlook's
        # folder pane, e.g. ["Work Blocks"]. Missing names are skipped silently.
        "additionalCalendars": [],
    },
    "settings": {
        "breakDurationMinutes": 10,
        "cooldownMinutes": 30,
        "challengeWordCount": 50,
    },
}

DEFAULT_STATE: dict = {
    "currentBreak": None,
    "lastBreakEndedAt": None,
    "editUnlockUntil": None,
    "manualFocus": None,
}

EDIT_UNLOCK_MINUTES = 5


def app_data_dir() -> Path:
    return Path.home() / ".app-blocker"


def config_path() -> Path:
    return app_data_dir() / "config.json"


def state_path() -> Path:
    return app_data_dir() / "state.json"


def words_path() -> Path:
    return Path(__file__).resolve().parent / "words.txt"


def load_or_create_config() -> dict:
    path = config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        return json.loads(json.dumps(DEFAULT_CONFIG))
    return json.loads(path.read_text())


def save_config(config: dict) -> None:
    """Atomic write: tempfile + rename."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, indent=2))
    tmp.replace(path)


def load_state() -> dict:
    path = state_path()
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_STATE))
    try:
        return json.loads(path.read_text())
    except Exception:
        return json.loads(json.dumps(DEFAULT_STATE))


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
