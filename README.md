# app-blocker

A personal program-blocker with a Cold-Turkey-style allowance break.

See [SPEC.md](../SPEC.md) for full design.

## Status

**Phase 0.5** — smoke test. The Tauri-based plan (see git tag `v0.0.1`) hit AppLocker on the work
laptop ("This app has been blocked by your system administrator"), so we pivoted to a
Python-script-based implementation that runs via the already-allowlisted `python.exe`.

## Run

Requires Python 3.9+ and Git on PATH. No Python dependencies needed.

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

## Optional speedup

```
pip install --user psutil
```

If `psutil` is importable, process enumeration uses it; otherwise it falls back to `tasklist`
(Windows) or `ps` (macOS).
