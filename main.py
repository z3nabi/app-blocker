"""App Blocker — Phase 0 smoke test.

Confirms that python + tkinter + process enumeration work on the target machine
(particularly the AppLocker-locked work laptop). Run with:

    python main.py

If a window opens listing running processes, the platform is viable.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import tkinter as tk
from tkinter import ttk


def list_processes_psutil() -> list[str]:
    import psutil  # type: ignore

    names = set()
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name")
        if name:
            names.add(name)
    return sorted(names, key=str.lower)


def list_processes_windows_tasklist() -> list[str]:
    out = subprocess.check_output(
        ["tasklist", "/FO", "CSV", "/NH"],
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    names = set()
    for line in out.splitlines():
        if not line.strip():
            continue
        first = line.split('","', 1)[0].lstrip('"')
        if first:
            names.add(first)
    return sorted(names, key=str.lower)


def list_processes_unix_ps() -> list[str]:
    out = subprocess.check_output(["ps", "-axco", "command"], text=True)
    lines = [l.strip() for l in out.splitlines()[1:] if l.strip()]
    return sorted(set(lines), key=str.lower)


def list_processes() -> tuple[list[str], str]:
    try:
        return list_processes_psutil(), "psutil"
    except ImportError:
        pass

    if sys.platform == "win32":
        return list_processes_windows_tasklist(), "tasklist (stdlib)"
    return list_processes_unix_ps(), "ps (stdlib)"


def main() -> None:
    procs, method = list_processes()

    root = tk.Tk()
    root.title("App Blocker — Phase 0 (Python)")
    root.geometry("520x600")

    header = ttk.Frame(root, padding=12)
    header.pack(fill=tk.X)

    ttk.Label(
        header,
        text="If you can see this window, Python + Tk works here.",
        font=("TkDefaultFont", 11, "bold"),
    ).pack(anchor=tk.W)

    info = (
        f"Python {sys.version.split()[0]} on {platform.system()} {platform.release()}\n"
        f"Process enumeration: {method} — found {len(procs)} unique process names"
    )
    ttk.Label(header, text=info, foreground="#555").pack(anchor=tk.W, pady=(4, 0))

    list_frame = ttk.Frame(root, padding=(12, 0, 12, 12))
    list_frame.pack(fill=tk.BOTH, expand=True)

    scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
    listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, activestyle="none")
    scrollbar.config(command=listbox.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    for name in procs:
        listbox.insert(tk.END, name)

    footer = ttk.Frame(root, padding=12)
    footer.pack(fill=tk.X)

    def refresh() -> None:
        new_procs, new_method = list_processes()
        listbox.delete(0, tk.END)
        for name in new_procs:
            listbox.insert(tk.END, name)
        info_label.config(
            text=f"Process enumeration: {new_method} — found {len(new_procs)} unique process names"
        )

    info_label = ttk.Label(header, text="", foreground="#555")
    ttk.Button(footer, text="Refresh", command=refresh).pack(side=tk.LEFT)
    ttk.Button(footer, text="Quit", command=root.destroy).pack(side=tk.RIGHT)

    root.mainloop()


if __name__ == "__main__":
    main()
