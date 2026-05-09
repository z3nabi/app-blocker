# Calendar-driven blocker (replaces static schedule)

**Date:** 2026-05-09
**Status:** approved (design); implementation pending

## Goal

Replace the static day/HH:MM schedule with a single rule driven by the user's Outlook calendar:

> **If a calendar event tagged with the Outlook Category "Deep Work" covers the current moment, block. Otherwise do not block.**

No AM/PM split, no lunch boundary, no meeting carve-outs. The rule is intentionally minimal; richer rule shapes are explicitly deferred ("for now" — see [Future work](#future-work)).

## Why

The static schedule is fragile: it hard-codes "block from 09:00–12:00 Mon–Fri" regardless of whether that morning is actually a deep-work morning or an all-day workshop. Tying blocking to calendar events lets the same source of truth (Outlook) drive both what the user has planned and whether the blocker is active.

## Constraints

- **Windows-only feature.** macOS is dev-only; the work calendar lives on the work laptop.
- **AppLocker-compatible.** All execution stays inside the allowlisted `python.exe`; no new binaries.
- **No Outlook auto-launch.** Outlook is itself a blocked app. Blindly calling `Dispatch("Outlook.Application")` would relaunch Outlook every tick and create a kill/relaunch loop. Use `GetActiveObject` exclusively — it raises if Outlook isn't already running.
- **Survive Outlook being killed.** During a Deep Work block, the blocker kills Outlook. The calendar layer must continue to make correct decisions afterward, using cached data.
- **Single user.** No accounts, no sync, no telemetry — consistent with `SPEC.md`.

## Architecture

A new module `outlook_calendar.py` owns all calendar concerns. It exposes a tiny public surface to the rest of `main.py` and hides Outlook/COM details. Cached events on disk decouple blocking decisions from live Outlook availability.

```
                ┌─────────────────────────────────────────────┐
                │ outlook_calendar.py                         │
                │                                             │
   tick (~1s)   │  current_deep_work_event(now) ──┐           │
   ────────────►│                                  │ reads    │
                │                                  ▼          │
                │                            ┌──────────┐     │
                │                            │ in-mem   │     │
                │                            │ cache    │     │
                │                            └────▲─────┘     │
                │                                 │ updates   │
                │                                 │           │
                │  ┌─── 60s daemon thread ────────┘           │
                │  │                                          │
                │  ▼                                          │
                │  GetActiveObject("Outlook.Application")     │
                │       (raises if Outlook not running)       │
                │                                             │
                │   on success → enumerate today's items,     │
                │                filter Categories=Deep Work, │
                │                update cache, persist to     │
                │                ~/.app-blocker/calendar-     │
                │                cache.json                   │
                │   on failure → leave cache untouched,       │
                │                update last_sync_status      │
                └─────────────────────────────────────────────┘
```

## Public interface

`outlook_calendar.py` exposes exactly:

```python
def current_deep_work_event(now: datetime) -> dict | None:
    """Return the Deep Work event covering `now`, or None."""

def last_sync_status() -> dict:
    """Return {"at": datetime|None, "ok": bool, "error": str|None}."""

def force_refresh() -> None:
    """Trigger an immediate sync attempt (for the UI 'Sync now' button)."""

def start_background_sync(interval_seconds: int = 60) -> None:
    """Start the daemon refresh thread. Idempotent."""
```

Everything else is private. The rest of `main.py` only knows about `current_deep_work_event` and the two status helpers — it never touches COM, never imports `win32com`.

## Components

### `outlook_calendar.py` (new file)
- Public functions above.
- Background daemon thread that wakes every `syncIntervalSeconds`, attempts one sync, and goes back to sleep.
- Pure helpers (unit-testable without COM): `_filter_events_by_category`, `_event_covers`, `_load_cache`, `_save_cache`, `_expand_all_day`.
- COM glue is isolated in a single function `_fetch_today_events_from_outlook()` that returns a list of plain dicts. This function is the only piece that touches `win32com.client`.

### `main.py` changes
- Drop `active_window`. Drop `"schedule"` from `DEFAULT_CONFIG`.
- Tick loop replaces `active_window(now, schedule)` with `outlook_calendar.current_deep_work_event(now)`. A non-`None` return means "block now."
- Schedule page (in the Tk UI) replaced by a Calendar page (read-only list of today's Deep Work events + sync status + "Sync now" button).
- `ScheduleWindowEditor` class deleted.
- Today-page hero meta line: "Deep work · ends 11:00" while active, else "No deep work blocks today" or "Next: 14:00".
- App startup calls `outlook_calendar.start_background_sync()`.
- Edit-lock (Phase 7) wiring continues to work — it asks "is a window active right now?", which is now answered by `current_deep_work_event` instead of `active_window`.

## Config schema

Add a `calendar` section to `~/.app-blocker/config.json`:

```json
{
  "calendar": {
    "deepWorkCategory": "Deep Work",
    "syncIntervalSeconds": 60
  }
}
```

`schedule` (the old day/HH:MM map) is ignored if present in an upgraded user's config — left in place for forward compatibility, not actively migrated or removed.

## Cache schema

Persisted to `~/.app-blocker/calendar-cache.json`. Rewritten in full on each successful sync.

```json
{
  "lastSyncAt": "2026-05-09T08:30:00",
  "lastSyncOk": true,
  "lastSyncError": null,
  "events": [
    {
      "start": "2026-05-09T09:00:00",
      "end":   "2026-05-09T11:00:00",
      "subject": "Focus block",
      "isAllDay": false
    }
  ]
}
```

`events` only contains today's events tagged Deep Work. Tomorrow's events aren't cached because the rule only consults "now". (Easy to extend if a future rule needs them.)

## Data flow

1. **App startup.** Load cache from disk into memory (treat missing/corrupt as empty). Call `start_background_sync()` to kick the daemon thread, which attempts an immediate first sync.
2. **Background daemon, every 60s.** Try `GetActiveObject("Outlook.Application")`. On success, enumerate today's calendar items, keep those whose Categories include the configured category. Outlook's `Categories` is a comma-separated string (e.g. `"Deep Work, Personal"`); split on comma, trim, and match the configured value against the resulting tokens (case-sensitive). Normalize each kept event into the cache event shape, write to in-memory cache, persist to disk. On any exception, capture it in `last_sync_status` and leave the cache untouched.
3. **Tick (~1s).** Blocker calls `current_deep_work_event(now)`. The function walks the in-memory cache and returns any event covering `now` (i.e. `event.start <= now < event.end`). All-day events are expanded to `[00:00 of start_date, 23:59:59 of end_date]` so a multi-day all-day Deep Work block covers every moment in its span. Returns `None` if no event covers now.
4. **Block decision.** If `current_deep_work_event(now)` is non-`None` and no allowance break is active, kill blocked apps as before.

## Error handling

| Failure | Behavior |
|---|---|
| Outlook not running (`GetActiveObject` raises COMError) | Sync status = "Outlook not open". Cache unchanged. **This is expected**, not an error condition. |
| COM call mid-query raises | Log to stderr; sync status = "Sync error: \<msg\>"; cache unchanged. |
| `pywin32` not installed (`import win32com` fails) | Calendar module disabled at import time. Blocker never blocks. Today page shows banner: "Install pywin32: `pip install --user pywin32`". |
| Cache file missing or invalid JSON | Start with empty in-memory cache. No error surfaced — first successful sync repopulates. |
| Non-Windows platform (macOS dev) | Calendar module disabled at import time. Blocker never blocks. No banner — this is dev-mode. |

The unifying principle: **a sync failure is never a hard failure for the app.** The blocker continues with whatever data it last had.

## UI changes

### Schedule page → Calendar page
A read-only view replacing the existing Schedule page in the tab list:
- Heading: "TODAY'S DEEP WORK BLOCKS"
- List of today's Deep Work events from the cache: `09:00–11:00  Focus block`
- Below the list: sync status line — "Last synced 30s ago" / "Outlook not open" / "Sync error: \<msg\>"
- "Sync now" button calls `force_refresh()`

### Today page
- Hero meta line:
  - During an active block: `Deep work · ends 11:00`
  - Outside any block: `No deep work blocks today` or `Next deep work: 14:00`
- `_summarize_schedule_today` is repurposed (or replaced) to read from the cache.

### Removed
- `ScheduleWindowEditor` class and its callers.

## Testing

### Unit tests (no COM)
- `_filter_events_by_category(events, "Deep Work")` — single-category event, multi-category event (`"Personal, Deep Work"`), missing category field, leading/trailing whitespace around the token, case-sensitivity (a category named `"deep work"` does NOT match).
- `_event_covers(event, now)` — boundary conditions: `now == start` (covered), `now == end` (not covered), single-day all-day event, multi-day all-day event spanning the current moment.
- Cache round-trip: `_save_cache` then `_load_cache` returns equivalent data.
- Corrupt cache file → empty cache, no exception.

### Integration test (Windows, manual)
1. Tag an Outlook event with the "Deep Work" category, starting in 2 minutes. Wait. Confirm blocker activates within 60s of the event's start time.
2. End the event (or wait for it). Confirm blocker deactivates within 60s of end time.
3. During an active block: close/kill Outlook. Confirm the block continues uninterrupted from the cache.
4. Start the app with Outlook closed. Confirm Calendar page shows "Outlook not open" and the blocker is inactive (no false blocks).
5. Open Outlook → confirm sync occurs within 60s and Calendar page populates.

## Migration

None. `schedule` field in existing configs is ignored. `state.json` is untouched. The first run after upgrade adds the `calendar` config section with defaults.

## Out of scope (future work)

Listed here to make explicit what was considered and intentionally left out:

- AM/PM-aware rules, lunch boundary, default-block-with-meeting-carveouts. The original brainstorm explored these but the user asked to ship the minimal "Deep Work blocks" rule first.
- Multiple categories or category combinations (e.g., "Comms" unblocks during meetings).
- Tomorrow's events, week ahead, look-ahead notifications.
- Honoring `BusyStatus` (Tentative / Free / OOF) — a Deep Work tag blocks regardless of busy status, by design.
- Reading from Microsoft Graph API or an `.ics` URL — would remove the "Outlook must be open at least once" caveat, but adds OAuth/proxy complexity and isn't worth it for v1.
- Calendar editing from inside app-blocker.

## Reference notes (existing integration)

The user has a working `win32com.client.gencache` reference (provided as a temporary `gencache_example.py` in the repo root, not committed). The implementation plan should mirror its shape with three required changes:

1. **`EnsureDispatch` → `GetActiveObject`.** The example uses `gencache.EnsureDispatch("Outlook.Application")`, which launches Outlook if not running. The new module **must not** launch Outlook (see [Constraints](#constraints)). Switch to `win32com.client.GetActiveObject("Outlook.Application")` and treat its `pywintypes.com_error` raise-on-no-instance as the "Outlook not open" branch.
2. **Filter by date range, not full scan.** The example iterates the whole calendar with `GetFirst()` / `GetNext()`. For "today's events" use `items.Restrict("[Start] >= '<today 00:00>' AND [Start] < '<tomorrow 00:00>'")` — Outlook's date format is locale-sensitive (e.g. `"05/09/2026 00:00"`), confirm during implementation.
3. **Read `item.Categories`.** The example doesn't touch this field. The new code keeps only items whose Categories string contains the configured token (see [Data flow](#data-flow), step 2).

The example's other patterns transfer as-is:
- `items.Sort("[Start]")` then `items.IncludeRecurrences = True` (in this order, before `Restrict`, so recurring Deep Work blocks expand into individual instances).
- `if item.Class == 26: ...` to narrow to `AppointmentItem` only (skips meetings, contact items, etc.).
- Wrap each item read in `try/except Exception: pass` for robustness against corrupted or permission-restricted items.
