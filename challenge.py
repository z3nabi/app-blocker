"""ChallengeModal — the typing challenge that gates allowance breaks."""

from __future__ import annotations

import tkinter as tk

from style import (
    ACCENT,
    F,
    INK,
    INK2,
    INK3,
    LINE,
    PAPER,
    PAPER_ALT,
    WARN,
    WHITE,
    _FONT_CACHE,
)


class ChallengeModal:
    def __init__(self, parent: tk.Tk, words: list[str], on_complete) -> None:
        self.words = words
        self.idx = 0
        self.on_complete = on_complete
        self._completed = False

        self.win = tk.Toplevel(parent)
        self.win.title("Allowance break — type to unlock")
        self.win.geometry("840x540")
        self.win.configure(bg=WHITE)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)

        outer = tk.Frame(self.win, bg=WHITE)
        outer.pack(fill=tk.BOTH, expand=True, padx=44, pady=32)

        tk.Label(outer, text=f"ALLOWANCE BREAK · {len(words)} WORDS",
                 bg=WHITE, fg=INK3, font=F("sans", 9, "bold"), anchor="w"
                 ).pack(anchor="w")
        tk.Label(outer, text=f"Type these {len(words)} words.",
                 bg=WHITE, fg=INK, font=F("serif", 26), anchor="w"
                 ).pack(anchor="w", pady=(4, 6))
        tk.Label(outer,
                 text="Space or Enter advances. Typos clear the current word and you start it over.",
                 bg=WHITE, fg=INK2, font=F("sans", 11),
                 wraplength=720, justify="left", anchor="w"
                 ).pack(anchor="w", pady=(0, 18))

        prog_row = tk.Frame(outer, bg=WHITE)
        prog_row.pack(fill=tk.X, pady=(0, 14))
        self.prog_canvas = tk.Canvas(prog_row, height=4, bg=LINE,
                                     highlightthickness=0)
        self.prog_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True,
                              padx=(0, 14))
        self.progress_var = tk.StringVar(value=self._progress_text())
        tk.Label(prog_row, textvariable=self.progress_var, bg=WHITE, fg=INK2,
                 font=F("mono", 11)).pack(side=tk.RIGHT)

        # Bottom-anchored widgets first so they can never be squeezed off the
        # screen by an over-tall middle widget. Pack order matters with
        # side=BOTTOM: the first call gets the very bottom slot.
        foot = tk.Frame(outer, bg=WHITE)
        foot.pack(side=tk.BOTTOM, fill=tk.X, pady=(14, 0))

        input_row = tk.Frame(outer, bg=WHITE,
                             highlightthickness=1, highlightbackground=INK)
        input_row.pack(side=tk.BOTTOM, fill=tk.X)

        word_card = tk.Frame(outer, bg=PAPER,
                             highlightthickness=1, highlightbackground=LINE)
        word_card.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 14))
        # height in lines — without this tk.Text defaults to 24, requesting
        # ~528px of vertical space which overflows the 540px modal and clips
        # the input row + Cancel button below it (Entry winds up unmapped,
        # so focus_force on it silently no-ops).
        self.text = tk.Text(
            word_card, wrap=tk.WORD,
            font=(_FONT_CACHE["serif"], 16),
            bg=PAPER, fg=INK2, padx=28, pady=24,
            relief="flat", borderwidth=0, highlightthickness=0,
            spacing1=4, spacing3=4,
            height=8,
        )
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.tag_configure("done", foreground=INK3)
        self.text.tag_configure(
            "current", foreground=INK, background=WHITE,
            font=(_FONT_CACHE["serif"], 16, "bold"),
        )
        self.text.tag_configure("pending", foreground=INK2)
        self._render_words()
        self.text.config(state=tk.DISABLED)
        input_pad = tk.Frame(input_row, bg=WHITE)
        input_pad.pack(fill=tk.X, padx=18, pady=14)
        tk.Label(input_pad, text="WORD", bg=WHITE, fg=INK3,
                 font=F("mono", 9, "bold")).pack(side=tk.LEFT)
        self.idx_label_var = tk.StringVar(value="01")
        tk.Label(input_pad, textvariable=self.idx_label_var,
                 bg=ACCENT, fg=WHITE, font=F("mono", 10, "bold"),
                 padx=8, pady=2).pack(side=tk.LEFT, padx=(8, 14))
        self.entry = tk.Entry(input_pad, font=F("mono", 16),
                              bg=WHITE, fg=INK,
                              relief="flat", borderwidth=0,
                              highlightthickness=0,
                              insertbackground=ACCENT)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<space>", self._on_separator)
        self.entry.bind("<Return>", self._on_separator)
        self.entry.bind("<KeyRelease>", self._on_keyrelease)
        self.entry.focus_set()

        tk.Button(
            foot, text="Cancel", command=self._cancel,
            bg=WHITE, fg=INK2, activebackground=PAPER_ALT,
            activeforeground=INK, font=F("sans", 10),
            relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=LINE,
            padx=14, pady=6, cursor="hand2",
        ).pack(side=tk.RIGHT)

        self._update_idx_label()
        self.prog_canvas.bind("<Configure>", lambda e: self._draw_progress())
        self._draw_progress()

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

    def _draw_progress(self) -> None:
        self.prog_canvas.delete("all")
        w = self.prog_canvas.winfo_width()
        if w < 4 or not self.words:
            return
        frac = self.idx / len(self.words)
        if frac > 0:
            self.prog_canvas.create_rectangle(
                0, 0, int(w * frac), 4, fill=ACCENT, outline=""
            )

    def _update_idx_label(self) -> None:
        n = len(self.words)
        cur = min(self.idx + 1, n)
        self.idx_label_var.set(f"{cur:02d} / {n}")

    def _render_words(self) -> None:
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        for i, word in enumerate(self.words):
            tag = "done" if i < self.idx else ("current" if i == self.idx else "pending")
            self.text.insert(tk.END, word, tag)
            self.text.insert(tk.END, " ")
        self.text.config(state=tk.DISABLED)
        try:
            self.text.see(f"1.0 + {sum(len(w) + 1 for w in self.words[:self.idx])} chars")
        except Exception:
            pass

    def _progress_text(self) -> str:
        return f"{self.idx:02d} / {len(self.words):02d}"

    def _flash_red(self) -> None:
        self.entry.config(foreground=WARN)
        self.entry.after(160, lambda: self.entry.config(foreground=INK))

    def _on_keyrelease(self, event):
        if event.keysym in ("space", "Return", "BackSpace", "Delete", "Left", "Right",
                            "Home", "End", "Tab", "Shift_L", "Shift_R", "Caps_Lock"):
            return
        if self.idx >= len(self.words):
            return
        typed = self.entry.get()
        if not typed:
            return
        target = self.words[self.idx].lower()
        if not target.startswith(typed.lower()):
            self.entry.delete(0, tk.END)
            self._flash_red()

    def _on_separator(self, event):
        typed = self.entry.get().strip()
        if not typed:
            return "break"
        target = self.words[self.idx]
        if typed.lower() == target.lower():
            self.idx += 1
            self.entry.delete(0, tk.END)
            self._render_words()
            self.progress_var.set(self._progress_text())
            self._update_idx_label()
            self._draw_progress()
            if self.idx >= len(self.words):
                self._complete()
        else:
            self._flash_red()
            self.entry.delete(0, tk.END)
        return "break"

    def _complete(self) -> None:
        if self._completed:
            return
        self._completed = True
        try:
            self.on_complete()
        finally:
            self.win.destroy()

    def _cancel(self) -> None:
        if not self._completed:
            self.win.destroy()
