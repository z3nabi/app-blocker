# app-blocker

A personal program-blocker with a Cold-Turkey-style allowance break.

See [SPEC.md](../SPEC.md) for full design.

## Status

**Phase 0.5** — smoke test. The Tauri-based plan (see git tag `v0.0.1`) hit AppLocker on the work
laptop ("This app has been blocked by your system administrator"), so we pivoted to a
Python-script-based implementation that runs via the already-allowlisted `python.exe`.

## Run

Requires Python 3.9+. No dependencies for the smoke test.

```
python main.py
```

A window should open showing running processes. If it does, the platform is viable.

## Optional speedup

```
pip install --user psutil
```

If `psutil` is importable, process enumeration uses it; otherwise it falls back to `tasklist`
(Windows) or `ps` (macOS).
