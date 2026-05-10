"""Visual style — Stillwater palette + typography (Direction A · Quiet)."""

from __future__ import annotations

import tkinter as tk


PAPER = "#FAF7F2"
PAPER_ALT = "#F2EEE6"
WHITE = "#FFFFFF"
INK = "#1F1D1A"
INK2 = "#5C5650"
INK3 = "#8E8780"
LINE = "#E5DFD4"
ACCENT = "#A8553A"
ACCENT_SOFT = "#EAD7CB"
OK_GREEN = "#5E7C45"
WARN = "#A8443A"

_FONT_CACHE: dict[str, str] = {
    "serif": "TkDefaultFont",
    "sans": "TkDefaultFont",
    "mono": "TkFixedFont",
}


def _pick_family(candidates: list[str], available: set[str]) -> str:
    for c in candidates:
        if c in available:
            return c
    return candidates[-1]


def init_fonts(root: tk.Tk) -> None:
    import tkinter.font as tkfont
    avail = set(tkfont.families(root))
    _FONT_CACHE["serif"] = _pick_family(
        ["Source Serif 4", "Source Serif Pro", "Iowan Old Style",
         "Cambria", "Georgia", "Times New Roman"], avail)
    _FONT_CACHE["sans"] = _pick_family(
        ["Inter", "Inter UI", "Segoe UI", "Helvetica Neue",
         "Helvetica", "Arial"], avail)
    _FONT_CACHE["mono"] = _pick_family(
        ["JetBrains Mono", "Cascadia Mono", "Cascadia Code",
         "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"], avail)


def F(role: str, size: int, weight: str = "normal", slant: str = "roman") -> tuple:
    return (_FONT_CACHE.get(role, "TkDefaultFont"), size, weight, slant)
