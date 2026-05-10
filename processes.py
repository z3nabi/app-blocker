"""Process enumeration, kill, and process-name normalization helpers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _normalize(name: str) -> str:
    n = name.strip().lower()
    if n.endswith(".exe"):
        n = n[:-4]
    return n


def collect_blocked_normalized(blocked_apps: list[dict]) -> set[str]:
    out: set[str] = set()
    for app in blocked_apps:
        for n in app.get("matchers", {}).get("names", []):
            out.add(_normalize(n))
    return out


def list_processes() -> tuple[list[tuple[int, str]], str]:
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None

    if psutil is not None:
        return (
            [
                (p.info["pid"], p.info["name"])
                for p in psutil.process_iter(["pid", "name"])
                if p.info.get("name")
            ],
            "psutil",
        )
    if sys.platform == "win32":
        return _list_windows_tasklist(), "tasklist"
    return _list_unix_ps(), "ps"


def _list_windows_tasklist() -> list[tuple[int, str]]:
    out = subprocess.check_output(
        ["tasklist", "/FO", "CSV", "/NH"], text=True, creationflags=CREATE_NO_WINDOW
    )
    result: list[tuple[int, str]] = []
    for line in out.splitlines():
        parts = line.split('","')
        if len(parts) < 2:
            continue
        name = parts[0].lstrip('"')
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        if name:
            result.append((pid, name))
    return result


def _list_unix_ps() -> list[tuple[int, str]]:
    out = subprocess.check_output(["ps", "-axco", "pid,command"], text=True)
    result: list[tuple[int, str]] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        result.append((pid, parts[1]))
    return result


def kill_pid(pid: int) -> bool:
    try:
        import psutil  # type: ignore

        psutil.Process(pid).kill()
        return True
    except ImportError:
        pass
    except Exception:
        return False
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                check=True,
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )
            return True
        except subprocess.CalledProcessError:
            return False
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False
