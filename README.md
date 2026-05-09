# app-blocker

A personal program-blocker with a Cold-Turkey-style allowance break.

See [SPEC.md](../SPEC.md) for full design.

## Status

**Phase 0.5** — smoke test. The Tauri-based plan (see git tag `v0.0.1`) hit AppLocker on the work
laptop ("This app has been blocked by your system administrator"), so we pivoted to a
Python-script-based implementation that runs via the already-allowlisted `python.exe`.

## Run

Requires Python 3.9+ and Git on PATH.

**On Windows (deploy target):** also install pywin32 — `pip install --user pywin32`. Required for the Outlook calendar integration.

**On macOS (dev only):** no extra dependencies; calendar integration is disabled and the blocker is inactive.

User config and state live in `~/.app-blocker/` (Mac) or `%USERPROFILE%\.app-blocker\` (Windows) — separate from the install dir, so updating code never touches them.

### One-time install

```
git clone https://github.com/z3nabi/app-blocker.git "%USERPROFILE%\app-blocker"   # Windows
git clone https://github.com/z3nabi/app-blocker.git "$HOME/app-blocker"           # macOS
```

### Launch (with update)

```
cd /d "%USERPROFILE%\app-blocker" && git pull && python main.py        # Windows
cd "$HOME/app-blocker" && git pull && python3 main.py                  # macOS
```

Drop that into a one-line `app-blocker.bat` (Windows) or `app-blocker.sh` (Mac) on your Desktop and double-click.

### Launch without updating

```
python "%USERPROFILE%\app-blocker\main.py"     # Windows
python3 "$HOME/app-blocker/main.py"            # macOS
```

## How blocking is scheduled

The blocker reads your Outlook calendar (via local COM, no network). Any event tagged with the Outlook Category "Deep Work" causes the configured apps to be killed for the duration of the event. Untag an event or end it early to lift the block immediately.

You must have Outlook open at least once after the app starts so the calendar can sync; the cache then survives Outlook being killed during a Deep Work block.

By default only your primary calendar is scanned. To also pick up secondary calendars (e.g. a private "Work Blocks" calendar your colleagues don't see), add their display names to `calendar.additionalCalendars` in `~/.app-blocker/config.json`:

```json
"calendar": {
  "deepWorkCategory": "Deep Work",
  "syncIntervalSeconds": 60,
  "additionalCalendars": ["Work Blocks"]
}
```

Names are matched case-insensitively against subfolders of your default Calendar and siblings at the mailbox root. Unknown names are ignored silently.

## Optional speedup

```
pip install --user psutil
```

If `psutil` is importable, process enumeration uses it; otherwise it falls back to `tasklist`
(Windows) or `ps` (macOS).
