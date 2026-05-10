"""AppPicker — modal that lists running processes for the block list."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from processes import list_processes


class AppPicker:
    def __init__(self, parent: tk.Tk, on_pick) -> None:
        self.on_pick = on_pick
        self.win = tk.Toplevel(parent)
        self.win.title("Add app to block list")
        self.win.geometry("460x520")
        self.win.transient(parent)
        self.win.grab_set()

        header = ttk.Frame(self.win, padding=(12, 12, 12, 4))
        header.pack(fill=tk.X)
        ttk.Label(header, text="Pick a running process to block:",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(header,
                  text="Tip: open the app you want to block first, then click Refresh.",
                  foreground="#666").pack(anchor="w", pady=(2, 0))

        search_row = ttk.Frame(self.win, padding=(12, 4, 12, 4))
        search_row.pack(fill=tk.X)
        ttk.Label(search_row, text="Filter:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._refilter())
        ttk.Entry(search_row, textvariable=self.search_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0)
        )

        list_frame = ttk.Frame(self.win, padding=(12, 4, 12, 8))
        list_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_frame)
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, activestyle="none")
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-Button-1>", lambda e: self._on_add())
        self.listbox.bind("<Return>", lambda e: self._on_add())

        btns = ttk.Frame(self.win, padding=(12, 0, 12, 12))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Refresh", command=self._refresh).pack(side=tk.LEFT)
        ttk.Button(btns, text="Cancel", command=self.win.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Add", command=self._on_add).pack(side=tk.RIGHT, padx=4)

        self._all: list[str] = []
        self._refresh()

        # Center on parent
        self.win.update_idletasks()
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            ww = self.win.winfo_width()
            wh = self.win.winfo_height()
            self.win.geometry(f"+{px + (pw - ww) // 2}+{py + (ph - wh) // 2}")
        except Exception:
            pass

    def _refresh(self) -> None:
        try:
            procs, _ = list_processes()
        except Exception:
            procs = []
        self._all = sorted({n for _, n in procs}, key=str.lower)
        self._refilter()

    def _refilter(self) -> None:
        q = self.search_var.get().lower().strip()
        self.listbox.delete(0, tk.END)
        for name in self._all:
            if q in name.lower():
                self.listbox.insert(tk.END, name)

    def _on_add(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        try:
            self.on_pick(name)
        finally:
            self.win.destroy()
