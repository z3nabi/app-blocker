"""Launch at login — install/uninstall plist (macOS) or .bat (Windows)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


LAUNCH_LABEL = "com.simon.appblocker"


def _main_py_path() -> Path:
    """Path to the entry point — main.py sits alongside this module."""
    return Path(__file__).resolve().parent / "main.py"


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"


def _windows_startup_path() -> Path:
    base = Path(os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    ))
    return base / "AppBlocker.bat"


def is_launch_at_login_installed() -> bool:
    if sys.platform == "darwin":
        return _macos_plist_path().exists()
    if sys.platform == "win32":
        return _windows_startup_path().exists()
    return False


def install_launch_at_login() -> tuple[bool, str]:
    main_py = _main_py_path()
    if sys.platform == "darwin":
        p = _macos_plist_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCH_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{main_py}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
'''
        p.write_text(plist)
        try:
            subprocess.run(["launchctl", "load", str(p)], check=False, capture_output=True)
        except Exception:
            pass
        return True, str(p)
    if sys.platform == "win32":
        # Use pythonw.exe so no console window flashes at login.
        pythonw = sys.executable
        if pythonw.lower().endswith("python.exe"):
            cand = Path(pythonw).with_name("pythonw.exe")
            if cand.exists():
                pythonw = str(cand)
        bat = f'@echo off\r\nstart "" "{pythonw}" "{main_py}"\r\n'
        p = _windows_startup_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(bat)
        return True, str(p)
    return False, "Launch-at-login not supported on this platform."


def uninstall_launch_at_login() -> tuple[bool, str]:
    if sys.platform == "darwin":
        p = _macos_plist_path()
        if p.exists():
            try:
                subprocess.run(["launchctl", "unload", str(p)], check=False, capture_output=True)
            except Exception:
                pass
            try:
                p.unlink()
            except OSError as e:
                return False, str(e)
        return True, ""
    if sys.platform == "win32":
        p = _windows_startup_path()
        if p.exists():
            try:
                p.unlink()
            except OSError as e:
                return False, str(e)
        return True, ""
    return False, "Launch-at-login not supported on this platform."
