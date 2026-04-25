"""Bootstrap launcher for app-blocker.

Downloads latest project zip from GitHub, extracts to ~/app-blocker
(or %USERPROFILE%\\app-blocker on Windows), then runs main.py from
there. Cross-platform, stdlib only.

Live alongside update-and-run.bat (Windows) or update-and-run.sh
(macOS/Linux). Each launch downloads fresh code; if the download
fails, errors loudly rather than silently running stale code.

Run directly with:
    python update_and_run.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from urllib.error import URLError


REPO = "z3nabi/app-blocker"
BRANCH = "main"
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"

INSTALL_DIR = Path.home() / "app-blocker"
TEMP_DIR = Path(tempfile.gettempdir())
ZIP_PATH = TEMP_DIR / "app-blocker.zip"
EXTRACT_TMP = TEMP_DIR / "app-blocker-extract"

UA = "Mozilla/5.0 (compatible; app-blocker-launcher)"
TIMEOUT = 60


def _log(msg: str) -> None:
    print(msg, flush=True)


def download_zip() -> bool:
    _log(f"[1/3] Downloading {ZIP_URL}")
    _log(f"      (urllib auto-detects system proxy on Windows / Mac)")
    if ZIP_PATH.exists():
        try:
            ZIP_PATH.unlink()
        except OSError:
            pass
    req = urllib.request.Request(ZIP_URL, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            with open(ZIP_PATH, "wb") as out:
                shutil.copyfileobj(resp, out)
    except URLError as e:
        _log(f"ERROR: download failed: {e}")
        _log("")
        _log("Possible fixes:")
        _log("  - Open https://github.com/" + REPO + " in your browser to authenticate")
        _log("    to your corporate proxy, then re-run this launcher.")
        _log("  - Set HTTPS_PROXY env var to a working proxy URL.")
        _log("  - Or download manually:")
        _log(f"        {ZIP_URL}")
        _log(f"      and save to {ZIP_PATH}, then re-run.")
        return False
    except Exception as e:
        _log(f"ERROR: unexpected download error: {e!r}")
        return False
    size_kb = ZIP_PATH.stat().st_size / 1024
    _log(f"      ok ({size_kb:.0f} KB)")
    return True


def extract_zip() -> bool:
    _log(f"[2/3] Extracting to {INSTALL_DIR}")
    if EXTRACT_TMP.exists():
        shutil.rmtree(EXTRACT_TMP, ignore_errors=True)
    EXTRACT_TMP.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(ZIP_PATH) as z:
            z.extractall(EXTRACT_TMP)
    except (zipfile.BadZipFile, OSError) as e:
        _log(f"ERROR: extract failed: {e}")
        return False

    children = [c for c in EXTRACT_TMP.iterdir() if c.is_dir()]
    if len(children) != 1:
        _log(f"ERROR: expected exactly one top-level dir in zip, got {len(children)}: {children}")
        return False
    extracted_root = children[0]

    if INSTALL_DIR.exists():
        try:
            shutil.rmtree(INSTALL_DIR)
        except OSError as e:
            _log(f"ERROR: could not clear existing install at {INSTALL_DIR}: {e}")
            return False

    try:
        shutil.move(str(extracted_root), str(INSTALL_DIR))
    except OSError as e:
        _log(f"ERROR: could not move install: {e}")
        return False

    shutil.rmtree(EXTRACT_TMP, ignore_errors=True)
    try:
        ZIP_PATH.unlink()
    except OSError:
        pass
    _log("      ok")
    return True


def run_main() -> int:
    main_py = INSTALL_DIR / "main.py"
    if not main_py.exists():
        _log(f"ERROR: {main_py} not found")
        return 1
    _log(f"[3/3] Running {main_py}")
    _log("")
    try:
        return subprocess.call([sys.executable, str(main_py)])
    except KeyboardInterrupt:
        return 0


def main() -> None:
    _log("=== app-blocker launcher ===")
    if not download_zip():
        sys.exit(1)
    if not extract_zip():
        sys.exit(1)
    sys.exit(run_main())


if __name__ == "__main__":
    main()
