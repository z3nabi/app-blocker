# app-blocker

A personal program-blocker with a Cold-Turkey-style allowance break.

See [SPEC.md](../SPEC.md) for full design.

## Status

**Phase 0.5** — smoke test. The Tauri-based plan (see git tag `v0.0.1`) hit AppLocker on the work
laptop ("This app has been blocked by your system administrator"), so we pivoted to a
Python-script-based implementation that runs via the already-allowlisted `python.exe`.

## Run

Requires Python 3.9+. No dependencies needed.

### Update-and-run launcher

Each launch pulls the latest from GitHub before running. If the download fails (e.g. corp proxy), it errors out loudly — no silent fallback to stale code.

**Windows:** save [update-and-run.bat](https://raw.githubusercontent.com/z3nabi/app-blocker/main/update-and-run.bat) anywhere (e.g. Desktop), double-click to launch.

**macOS/Linux:** save [update-and-run.sh](https://raw.githubusercontent.com/z3nabi/app-blocker/main/update-and-run.sh), `chmod +x update-and-run.sh`, then `./update-and-run.sh`.

### Run last install (no update)

After the launcher has run at least once, the code lives at `~/app-blocker/` (Mac) or `%USERPROFILE%\app-blocker\` (Windows). Run it directly to skip the download:

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
