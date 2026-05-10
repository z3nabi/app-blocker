"""Pure formatting helpers used by the Today/Calendar UI."""

from __future__ import annotations

from datetime import datetime

import outlook_calendar


def _summarize_blocked(config: dict) -> str:
    apps = config.get("blockedApps", [])
    if not apps:
        return "(no apps configured)"
    names: list[str] = []
    for app in apps:
        names.extend(app.get("matchers", {}).get("names", []))
    return ", ".join(names) if names else "(no matchers)"


def _summarize_calendar_today(now: datetime) -> str:
    """Hero-meta line for the Today page: describes the next/current Deep Work block."""
    current = outlook_calendar.current_deep_work_event(now)
    if current is not None:
        try:
            end = datetime.fromisoformat(current["end"])
            return f"Deep work · ends {end.strftime('%H:%M')}"
        except (KeyError, ValueError):
            return "Deep work · in progress"
    # Look ahead for today's next Deep Work block.
    cache = outlook_calendar._snapshot_cache()
    upcoming = []
    for ev in cache.get("events", []):
        try:
            # Strip tzinfo: pywintypes emits tz-aware ISO strings, but `now` is
            # naive (datetime.now()). Same defense as outlook_calendar._event_covers.
            start = datetime.fromisoformat(ev["start"]).replace(tzinfo=None)
            if start > now and start.date() == now.date():
                upcoming.append((start, ev))
        except (KeyError, ValueError):
            continue
    upcoming.sort(key=lambda pair: pair[0])
    if upcoming:
        return f"Next deep work: {upcoming[0][0].strftime('%H:%M')}"
    return "No deep work blocks today"


def _format_remaining(seconds: float) -> str:
    if seconds <= 0:
        return "0:00"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"
