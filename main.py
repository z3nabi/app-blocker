"""App Blocker — Outlook-calendar-driven blocker with allowance-break challenge.

Config:    ~/.app-blocker/config.json   (user-editable; in-app editor too)
State:     ~/.app-blocker/state.json    (managed by app — current break, last
                                         break end for cooldown)
Wordlist:  words.txt next to this file (or embedded fallback)

Run:
    python main.py     (Windows)
    python3 main.py    (macOS)
"""

from __future__ import annotations

import json
import platform
import random
import sys
import time
import tkinter as tk
import uuid
from datetime import date, datetime
from pathlib import Path
from tkinter import messagebox, ttk

import outlook_calendar
import tray
from app_picker import AppPicker
from autostart import (
    install_launch_at_login,
    is_launch_at_login_installed,
    uninstall_launch_at_login,
)
from challenge import ChallengeModal
from killer import KillerThread
from paths import config_path, load_or_create_config, save_config, state_path
from style import (
    ACCENT,
    F,
    INK,
    INK2,
    INK3,
    LINE,
    OK_GREEN,
    PAPER,
    PAPER_ALT,
    WARN,
    WHITE,
    _FONT_CACHE,
    init_fonts,
)
from summaries import _format_remaining, _summarize_calendar_today
from wordlist import load_wordlist


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------


class MainWindow:
    def __init__(self) -> None:
        load_or_create_config()
        self.wordlist, self.wordlist_source = load_wordlist()

        self.killer = KillerThread()
        self.killer.start()
        self.started_at = time.monotonic()

        self.root = tk.Tk()
        self._setup_root()
        self._setup_styles()

        self.tray_icon: tray.TrayIcon | None = None
        self._setup_tray()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Unmap>", self._on_unmap)

        # ---- Shell: sidebar | content ----
        shell = tk.Frame(self.root, bg=PAPER)
        shell.pack(fill=tk.BOTH, expand=True)
        self.sidebar = tk.Frame(shell, bg=PAPER, width=216)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        tk.Frame(shell, bg=LINE, width=1).pack(side=tk.LEFT, fill=tk.Y)
        self.content = tk.Frame(shell, bg=WHITE)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.current_page = tk.StringVar(value="today")
        self.pages: dict[str, tk.Frame] = {}
        self.nav_widgets: dict[str, dict] = {}

        self._build_sidebar()
        self._build_today_page()
        self._build_calendar_page()
        self._build_blocks_page()
        self._build_settings_page()

        self._set_page("today")
        self._start_calendar_sync()
        self._refresh()

    def run(self) -> None:
        self.root.mainloop()

    # -- root + styles ----------------------------------------------------

    def _setup_root(self) -> None:
        self.root.title("Stillwater · App Blocker")
        self.root.geometry("1100x720")
        self.root.minsize(940, 600)
        self.root.configure(bg=PAPER)
        init_fonts(self.root)

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Treeview",
            background=WHITE, foreground=INK, fieldbackground=WHITE,
            bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
            font=F("sans", 10), rowheight=26, borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=PAPER, foreground=INK2,
            font=F("sans", 9, "bold"), bordercolor=LINE, relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", PAPER_ALT)],
            foreground=[("selected", INK)],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=PAPER, troughcolor=PAPER_ALT,
            bordercolor=PAPER, arrowcolor=INK2,
            lightcolor=PAPER, darkcolor=PAPER,
        )

    def _setup_tray(self) -> None:
        if not (tray.HAVE_WIN32 and sys.platform == "win32"):
            return
        try:
            icon_path = Path(__file__).resolve().parent / "assets" / "stillwater.ico"
            self.tray_icon = tray.TrayIcon(
                title="Stillwater · App Blocker",
                on_show=lambda: self.root.after(0, self._restore_window),
                on_quit=lambda: self.root.after(0, self._quit_app),
                icon_path=icon_path if icon_path.is_file() else None,
            )
            self.tray_icon.start()
        except Exception:
            self.tray_icon = None

    # -- window lifecycle -------------------------------------------------

    def _restore_window(self) -> None:
        try:
            self.root.deiconify()
        except tk.TclError:
            return
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def _quit_app(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.stop()
        self.killer.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        if self.tray_icon is not None:
            self.root.withdraw()
        else:
            self._quit_app()

    def _on_unmap(self, event) -> None:
        if event.widget is self.root and self.tray_icon is not None:
            try:
                if self.root.state() == "iconic":
                    self.root.withdraw()
            except tk.TclError:
                pass

    # -- shared widget helpers --------------------------------------------

    def _make_button(self, parent, text, command) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command,
            bg=INK, fg=WHITE, activebackground=INK2, activeforeground=WHITE,
            disabledforeground=INK3,
            font=F("sans", 10), padx=18, pady=8,
            relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=INK,
            cursor="hand2",
        )

    def _set_button_enabled(self, btn: tk.Button, enabled: bool) -> None:
        # Toggle visual + interactive state. tk.Button's default disabled
        # rendering only dims the foreground; we also flip bg/border/cursor
        # so the difference is unmistakable on this palette.
        if enabled:
            btn.config(state=tk.NORMAL, bg=INK, fg=WHITE,
                       highlightbackground=INK, cursor="hand2")
        else:
            btn.config(state=tk.DISABLED, bg=PAPER, fg=INK3,
                       highlightbackground=LINE, cursor="arrow")

    # -- challenge entry points -------------------------------------------

    def _challenge_word_count(self) -> int:
        n = int(self.killer._settings().get("challengeWordCount", 50))
        return max(1, min(n, len(self.wordlist)))

    def _open_challenge(self) -> None:
        ok, _reason = self.killer.can_take_break()
        if not ok:
            return
        words = random.sample(self.wordlist, self._challenge_word_count())
        ChallengeModal(self.root, words, on_complete=self.killer.start_break)

    def _open_edit_unlock_challenge(self) -> None:
        if not self.killer.is_edit_locked():
            return
        words = random.sample(self.wordlist, self._challenge_word_count())
        ChallengeModal(self.root, words, on_complete=self.killer.start_edit_unlock)

    # -- sidebar ----------------------------------------------------------

    def _build_sidebar(self) -> None:
        brand = tk.Frame(self.sidebar, bg=PAPER)
        brand.pack(fill=tk.X, padx=22, pady=(24, 22))
        tk.Label(
            brand, text="Stillwater", bg=PAPER, fg=INK,
            font=(_FONT_CACHE["serif"], 19, "normal", "italic"),
        ).pack(anchor="w")

        nav_holder = tk.Frame(self.sidebar, bg=PAPER)
        nav_holder.pack(fill=tk.X, padx=12)

        nav_items = [
            ("today", "Today"),
            ("calendar", "Calendar"),
            ("blocks", "Block lists"),
            ("settings", "Settings"),
        ]
        for key, label in nav_items:
            # Single-widget row: one Label that fills the whole sidebar width.
            # macOS Tk hit-testing across nested frames + multiple click
            # targets is unreliable; collapsing to one widget per row makes
            # the click target unambiguous.
            lbl = tk.Label(
                nav_holder, text=label, bg=PAPER, fg=INK2,
                font=F("sans", 11), padx=12, pady=8, anchor="w",
                cursor="hand2",
            )
            lbl.pack(fill=tk.X)
            click = (lambda k=key: lambda e: self._set_page(k))()
            lbl.bind("<Button-1>", click)
            lbl.bind("<ButtonRelease-1>", click)
            self.nav_widgets[key] = {"label": lbl, "base_text": label}

        sb_strip = tk.Frame(self.sidebar, bg=PAPER)
        sb_strip.pack(side=tk.BOTTOM, fill=tk.X, padx=22, pady=(0, 22))
        tk.Frame(sb_strip, bg=LINE, height=1).pack(fill=tk.X, pady=(0, 14))
        tk.Label(
            sb_strip, text="ACTIVE BLOCK", bg=PAPER, fg=INK3,
            font=F("sans", 9, "bold"), anchor="w",
        ).pack(fill=tk.X)
        self.sb_label_var = tk.StringVar(value="None")
        tk.Label(
            sb_strip, textvariable=self.sb_label_var, bg=PAPER, fg=INK,
            font=F("serif", 14), anchor="w",
        ).pack(fill=tk.X, pady=(4, 0))
        self.sb_sub_var = tk.StringVar(value="")
        tk.Label(
            sb_strip, textvariable=self.sb_sub_var, bg=PAPER, fg=INK2,
            font=F("mono", 10), anchor="w",
        ).pack(fill=tk.X, pady=(2, 0))

    def _set_page(self, key: str) -> None:
        self.current_page.set(key)
        self._update_nav_visual()
        for k, frame in self.pages.items():
            if k == key:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()

    def _update_nav_visual(self) -> None:
        for k, w in self.nav_widgets.items():
            active = (k == self.current_page.get())
            bg = PAPER_ALT if active else PAPER
            fg = INK if active else INK2
            font = F("sans", 11, "bold" if active else "normal")
            w["label"].config(bg=bg, fg=fg, font=font)

    # -- Today page -------------------------------------------------------

    def _build_today_page(self) -> None:
        today_page = tk.Frame(self.content, bg=WHITE)
        self.pages["today"] = today_page
        # Scrollable Today: Canvas + Scrollbar wrap a padded inner frame so
        # content overflowing the window height can be scrolled.
        self._today_canvas = tk.Canvas(today_page, bg=WHITE, highlightthickness=0)
        today_vsb = ttk.Scrollbar(today_page, orient="vertical", command=self._today_canvas.yview)
        self._today_canvas.configure(yscrollcommand=today_vsb.set)
        today_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._today_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        today_padframe = tk.Frame(self._today_canvas, bg=WHITE)
        self._today_padframe_id = self._today_canvas.create_window(
            (0, 0), window=today_padframe, anchor="nw")
        today_inner = tk.Frame(today_padframe, bg=WHITE)
        today_inner.pack(fill=tk.BOTH, expand=True, padx=48, pady=36)

        today_padframe.bind("<Configure>", self._on_today_padframe_configure)
        self._today_canvas.bind("<Configure>", self._on_today_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._on_today_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._on_today_button4, add="+")
        self.root.bind_all("<Button-5>", self._on_today_button5, add="+")

        self.today_date_var = tk.StringVar(value="")
        tk.Label(
            today_inner, textvariable=self.today_date_var, bg=WHITE, fg=INK3,
            font=F("sans", 9, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            today_inner, text="Today.", bg=WHITE, fg=INK,
            font=F("serif", 30), anchor="w",
        ).pack(anchor="w", pady=(4, 22))

        hero = tk.Frame(
            today_inner, bg=PAPER,
            highlightthickness=1, highlightbackground=LINE,
        )
        hero.pack(fill=tk.X, pady=(0, 22))
        hero_l = tk.Frame(hero, bg=PAPER)
        hero_l.pack(side=tk.LEFT, padx=28, pady=22, fill=tk.X, expand=True)
        pill_row = tk.Frame(hero_l, bg=PAPER)
        pill_row.pack(anchor="w")
        self.pill_dot = tk.Frame(pill_row, bg=ACCENT, width=6, height=6)
        self.pill_dot.pack(side=tk.LEFT, pady=(3, 0))
        self.pill_var = tk.StringVar(value="")
        self.pill_label = tk.Label(
            pill_row, textvariable=self.pill_var, bg=PAPER, fg=ACCENT,
            font=F("sans", 9, "bold"),
        )
        self.pill_label.pack(side=tk.LEFT, padx=8)
        self.hero_session_var = tk.StringVar(value="No active block")
        tk.Label(
            hero_l, textvariable=self.hero_session_var, bg=PAPER, fg=INK,
            font=F("serif", 24), anchor="w",
        ).pack(anchor="w", pady=(10, 4))
        self.hero_meta_var = tk.StringVar(value="")
        tk.Label(
            hero_l, textvariable=self.hero_meta_var, bg=PAPER, fg=INK2,
            font=F("sans", 11), anchor="w",
        ).pack(anchor="w")
        hero_r = tk.Frame(hero, bg=PAPER)
        hero_r.pack(side=tk.RIGHT, padx=32, pady=22)
        self.hero_time_var = tk.StringVar(value="—")
        tk.Label(
            hero_r, textvariable=self.hero_time_var, bg=PAPER, fg=INK,
            font=F("serif", 44), anchor="e",
        ).pack(anchor="e")
        tk.Label(
            hero_r, text="REMAINING", bg=PAPER, fg=INK3,
            font=F("sans", 9, "bold"),
        ).pack(anchor="e", pady=(2, 0))

        actions_row = tk.Frame(today_inner, bg=WHITE)
        actions_row.pack(fill=tk.X, pady=(0, 22))
        # Inner holder packed without fill/anchor → x-centered in actions_row.
        actions_inner = tk.Frame(actions_row, bg=WHITE)
        actions_inner.pack()

        self.focus_30_btn = self._make_button(
            actions_inner, "Focus 30 min", lambda: self._start_focus(30),
        )
        self.focus_30_btn.pack(side=tk.LEFT)
        self.focus_60_btn = self._make_button(
            actions_inner, "Focus 60 min", lambda: self._start_focus(60),
        )
        # Tight pair, then a wider gap before the conceptually-distinct allowance.
        self.focus_60_btn.pack(side=tk.LEFT, padx=(6, 28))
        self.break_btn = self._make_button(
            actions_inner, "Allowance break", self._open_challenge,
        )
        self.break_btn.pack(side=tk.LEFT)

        self.allowance_caption_var = tk.StringVar(value="")
        tk.Label(
            actions_row, textvariable=self.allowance_caption_var, bg=WHITE, fg=INK3,
            font=F("sans", 10),
        ).pack(pady=(8, 0))

        stats_grid = tk.Frame(
            today_inner, bg=LINE,
            highlightthickness=1, highlightbackground=LINE,
        )
        stats_grid.pack(fill=tk.X, pady=(0, 24))
        for i in range(3):
            stats_grid.columnconfigure(i, weight=1, uniform="stat")
        self.stat_kills_var = tk.StringVar(value="0")
        self.stat_kills_sub_var = tk.StringVar(value="attempts")
        self.stat_uptime_var = tk.StringVar(value="—")
        self.stat_uptime_sub_var = tk.StringVar(value="uptime")
        self.stat_cooldown_var = tk.StringVar(value="—")
        self.stat_cooldown_sub_var = tk.StringVar(value="allowance")
        self._stat_cell(stats_grid, 0, "BLOCKED", self.stat_kills_var, self.stat_kills_sub_var)
        self._stat_cell(stats_grid, 1, "RUNNING", self.stat_uptime_var, self.stat_uptime_sub_var)
        self._stat_cell(stats_grid, 2, "ALLOWANCE", self.stat_cooldown_var, self.stat_cooldown_sub_var)

        today_section_h = tk.Frame(today_inner, bg=WHITE)
        today_section_h.pack(fill=tk.X)
        tk.Label(
            today_section_h, text="Recent activity", bg=WHITE, fg=INK,
            font=F("serif", 16), anchor="w",
        ).pack(side=tk.LEFT)

        last_killed_card = tk.Frame(
            today_inner, bg=PAPER,
            highlightthickness=1, highlightbackground=LINE,
        )
        last_killed_card.pack(fill=tk.X, pady=(10, 12))
        self.last_killed_var = tk.StringVar(value="No kills yet.")
        tk.Label(
            last_killed_card, textvariable=self.last_killed_var,
            bg=PAPER, fg=INK2, font=F("mono", 10),
            anchor="w", justify="left", wraplength=900,
        ).pack(fill=tk.X, padx=20, pady=14)

        self.diag_var = tk.StringVar(value="")
        tk.Label(
            today_inner, textvariable=self.diag_var, bg=WHITE, fg=INK3,
            font=F("mono", 9), anchor="w", justify="left",
        ).pack(anchor="w", pady=(4, 0))
        self.err_var = tk.StringVar(value="")
        tk.Label(
            today_inner, textvariable=self.err_var, bg=WHITE, fg=WARN,
            font=F("sans", 10), anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # DEV-ONLY: reset button. Remove before shipping for real use.
        self._make_button(
            today_inner, "Reset break/cooldown [dev]", self._reset_state,
        ).pack(anchor="e", pady=(16, 0))

    def _stat_cell(self, parent, col, label, val_var, sub_var) -> None:
        c = tk.Frame(parent, bg=WHITE)
        c.grid(
            row=0, column=col, sticky="nsew",
            padx=(0 if col == 0 else 1, 0), pady=0,
        )
        tk.Label(
            c, text=label, bg=WHITE, fg=INK3,
            font=F("sans", 9, "bold"), anchor="w",
        ).pack(anchor="w", padx=22, pady=(20, 6))
        tk.Label(
            c, textvariable=val_var, bg=WHITE, fg=INK,
            font=F("serif", 26), anchor="w",
        ).pack(anchor="w", padx=22)
        tk.Label(
            c, textvariable=sub_var, bg=WHITE, fg=INK2,
            font=F("sans", 10), anchor="w",
        ).pack(anchor="w", padx=22, pady=(2, 20))

    def _on_today_padframe_configure(self, _e) -> None:
        self._today_canvas.configure(scrollregion=self._today_canvas.bbox("all"))

    def _on_today_canvas_configure(self, e) -> None:
        # Track canvas width so the padded inner frame fills the viewport.
        self._today_canvas.itemconfigure(self._today_padframe_id, width=e.width)

    def _on_today_mousewheel(self, e) -> None:
        if self.current_page.get() != "today":
            return
        # macOS sends small deltas; Windows sends multiples of 120.
        if sys.platform == "darwin":
            self._today_canvas.yview_scroll(-1 * e.delta, "units")
        else:
            self._today_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def _on_today_button4(self, _e) -> None:
        if self.current_page.get() == "today":
            self._today_canvas.yview_scroll(-1, "units")

    def _on_today_button5(self, _e) -> None:
        if self.current_page.get() == "today":
            self._today_canvas.yview_scroll(1, "units")

    def _start_focus(self, minutes: int) -> None:
        if self.killer.manual_focus_window() is not None:
            return
        if outlook_calendar.current_deep_work_event(datetime.now()) is not None:
            return
        if self.killer.is_break_active():
            return
        if not messagebox.askyesno(
            "Start focus session",
            f"Start a {minutes}-minute focus session now?\n\n"
            "Blocked apps will be killed for the duration. "
            "An allowance break will require the usual word challenge.",
            parent=self.root,
        ):
            return
        self.killer.start_manual_focus(minutes)

    def _reset_state(self) -> None:
        if not messagebox.askyesno(
            "Reset break / cooldown",
            "Clear any active break and cooldown? "
            "(Dev-only soft-mode bypass.)",
            parent=self.root,
        ):
            return
        self.killer.reset_break_state()

    # -- Calendar page ----------------------------------------------------

    def _build_calendar_page(self) -> None:
        calendar_page = tk.Frame(self.content, bg=WHITE)
        self.pages["calendar"] = calendar_page
        self.cal_inner = tk.Frame(calendar_page, bg=WHITE)
        self.cal_inner.pack(fill="both", expand=True, padx=24, pady=24)

        tk.Label(
            self.cal_inner, text="TODAY'S DEEP WORK BLOCKS", bg=WHITE, fg=INK3,
            font=(_FONT_CACHE["sans"], 11, "bold"),
        ).pack(anchor="w", pady=(0, 12))

        self.cal_list_frame = tk.Frame(self.cal_inner, bg=WHITE)
        self.cal_list_frame.pack(fill="x", anchor="w")

        self.cal_status_var = tk.StringVar(value="")

        tk.Frame(self.cal_inner, bg=LINE, height=1).pack(fill="x", pady=(20, 12))
        tk.Label(self.cal_inner, textvariable=self.cal_status_var, bg=WHITE, fg=INK3,
                 font=(_FONT_CACHE["sans"], 11)).pack(anchor="w")

        tk.Button(self.cal_inner, text="Sync now", command=self._on_sync_now,
                  bg=PAPER_ALT, fg=INK, relief="flat",
                  font=(_FONT_CACHE["sans"], 11)).pack(anchor="w", pady=(12, 0))

        self._refresh_calendar_page()

    def _refresh_calendar_page(self) -> None:
        for child in self.cal_list_frame.winfo_children():
            child.destroy()
        cache = outlook_calendar._snapshot_cache()
        # Filter explicitly: cache may hold prior-day events if no successful
        # sync has run today (e.g., Outlook closed at startup).
        todays = outlook_calendar.events_on_date(cache.get("events", []), date.today())
        if not todays:
            tk.Label(
                self.cal_list_frame, text="No Deep Work events today.", bg=WHITE, fg=INK2,
                font=(_FONT_CACHE["serif"], 14),
            ).pack(anchor="w")
        else:
            for start, ev in todays:
                try:
                    end = datetime.fromisoformat(ev["end"]).replace(tzinfo=None)
                except (KeyError, ValueError):
                    continue
                line = f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}    {ev.get('subject', '')}"
                tk.Label(self.cal_list_frame, text=line, bg=WHITE, fg=INK,
                         font=(_FONT_CACHE["serif"], 14)).pack(anchor="w", pady=2)
        status = outlook_calendar.last_sync_status()
        if status["ok"]:
            self.cal_status_var.set(f"Last synced at {status['at']}")
        elif status["error"]:
            self.cal_status_var.set(status["error"])
        else:
            self.cal_status_var.set("Never synced")

    def _on_sync_now(self) -> None:
        outlook_calendar.force_refresh()
        # Give the sync thread a brief moment, then refresh the page.
        self.cal_inner.after(500, self._refresh_calendar_page)

    # -- Block lists page -------------------------------------------------

    def _build_blocks_page(self) -> None:
        blocks_page = tk.Frame(self.content, bg=WHITE)
        self.pages["blocks"] = blocks_page
        blocks_inner = tk.Frame(blocks_page, bg=WHITE)
        blocks_inner.pack(fill=tk.BOTH, expand=True, padx=48, pady=36)

        tk.Label(
            blocks_inner, text="BLOCK LISTS", bg=WHITE, fg=INK3,
            font=F("sans", 9, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            blocks_inner, text="Process names to silence.",
            bg=WHITE, fg=INK, font=F("serif", 26), anchor="w",
        ).pack(anchor="w", pady=(4, 8))
        tk.Label(
            blocks_inner,
            text="Killed during active Deep Work calendar events. Edit the JSON config for advanced matchers.",
            bg=WHITE, fg=INK2, font=F("sans", 11), anchor="w",
            wraplength=720, justify="left",
        ).pack(anchor="w", pady=(0, 22))

        self.blocks_lock_banner = tk.Frame(
            blocks_inner, bg=PAPER_ALT,
            highlightthickness=1, highlightbackground=LINE,
        )
        self.blocks_lock_label = tk.Label(
            self.blocks_lock_banner, bg=PAPER_ALT, fg=INK,
            text="List frozen during active block.",
            font=F("sans", 11), anchor="w",
        )
        self.blocks_lock_label.pack(side=tk.LEFT, padx=14, pady=10)
        self.blocks_unlock_btn = self._make_button(
            self.blocks_lock_banner, "Unlock to edit", self._open_edit_unlock_challenge,
        )
        self.blocks_unlock_btn.pack(side=tk.RIGHT, padx=10, pady=8)

        self.blocks_card = tk.Frame(
            blocks_inner, bg=WHITE,
            highlightthickness=1, highlightbackground=LINE,
        )
        self.blocks_card.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        apps_scroll = ttk.Scrollbar(self.blocks_card)
        self.apps_listbox = tk.Listbox(
            self.blocks_card, yscrollcommand=apps_scroll.set,
            activestyle="none", relief="flat", borderwidth=0,
            bg=WHITE, fg=INK, font=F("sans", 11),
            highlightthickness=0,
            selectbackground=PAPER_ALT, selectforeground=INK,
        )
        apps_scroll.config(command=self.apps_listbox.yview)
        apps_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1))
        self.apps_listbox.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=10,
        )

        self.displayed_app_ids: list[str] = []

        blocks_btns = tk.Frame(blocks_inner, bg=WHITE)
        blocks_btns.pack(fill=tk.X)
        self.apps_add_btn = self._make_button(blocks_btns, "Add…", self._add_app_via_picker)
        self.apps_remove_btn = self._make_button(blocks_btns, "Remove selected", self._remove_selected_app)
        self.apps_add_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.apps_remove_btn.pack(side=tk.LEFT)

    def _refresh_apps_list(self) -> None:
        snap = self.killer.snapshot()
        apps = snap["config"].get("blockedApps", [])
        sel = self.apps_listbox.curselection()
        sel_idx = sel[0] if sel else None
        self.apps_listbox.delete(0, tk.END)
        self.displayed_app_ids.clear()
        for app in apps:
            display = app.get("displayName", "(unnamed)")
            names = app.get("matchers", {}).get("names", [])
            self.apps_listbox.insert(tk.END, f"{display}  —  {', '.join(names)}")
            self.displayed_app_ids.append(app.get("id", ""))
        if sel_idx is not None and sel_idx < len(apps):
            self.apps_listbox.selection_set(sel_idx)

    def _add_app_via_picker(self) -> None:
        def on_pick(name: str) -> None:
            snap = self.killer.snapshot()
            cfg = json.loads(json.dumps(snap["config"]))
            cfg.setdefault("blockedApps", []).append({
                "id": str(uuid.uuid4()),
                "displayName": name,
                "matchers": {"names": [name]},
            })
            save_config(cfg)
        AppPicker(self.root, on_pick=on_pick)

    def _remove_selected_app(self) -> None:
        sel = self.apps_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self.displayed_app_ids):
            return
        app_id = self.displayed_app_ids[idx]
        snap = self.killer.snapshot()
        cfg = json.loads(json.dumps(snap["config"]))
        cfg["blockedApps"] = [
            a for a in cfg.get("blockedApps", []) if a.get("id") != app_id
        ]
        save_config(cfg)

    # -- Settings page ----------------------------------------------------

    def _build_settings_page(self) -> None:
        settings_page = tk.Frame(self.content, bg=WHITE)
        self.pages["settings"] = settings_page
        s_inner = tk.Frame(settings_page, bg=WHITE)
        s_inner.pack(fill=tk.BOTH, expand=True, padx=48, pady=36)

        tk.Label(
            s_inner, text="SETTINGS", bg=WHITE, fg=INK3,
            font=F("sans", 9, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            s_inner, text="Tuning.", bg=WHITE, fg=INK,
            font=F("serif", 26), anchor="w",
        ).pack(anchor="w", pady=(4, 22))

        s_card = tk.Frame(
            s_inner, bg=PAPER,
            highlightthickness=1, highlightbackground=LINE,
        )
        s_card.pack(fill=tk.X, pady=(0, 14))
        self.s_grid = tk.Frame(s_card, bg=PAPER)
        self.s_grid.pack(fill=tk.X, padx=28, pady=22)

        self.break_var = tk.IntVar(value=10)
        self.cooldown_var = tk.IntVar(value=30)
        self.words_var = tk.IntVar(value=50)
        self._settings_loading = False
        self.spinboxes: list[tk.Spinbox] = []

        self._add_setting_row(0, "Break duration", self.break_var, 1, 240, "minutes")
        self._add_setting_row(1, "Cooldown after break", self.cooldown_var, 0, 240, "minutes")
        self._add_setting_row(2, "Challenge word count", self.words_var, 1, len(self.wordlist), "words")
        tk.Label(
            s_inner, text="Saves on focus-out, Enter, or arrow click.",
            bg=WHITE, fg=INK3, font=F("sans", 10, "italic"), anchor="w",
        ).pack(anchor="w")

        launch_card = tk.Frame(
            s_inner, bg=PAPER,
            highlightthickness=1, highlightbackground=LINE,
        )
        launch_card.pack(fill=tk.X, pady=(18, 0))
        launch_pad = tk.Frame(launch_card, bg=PAPER)
        launch_pad.pack(fill=tk.X, padx=28, pady=20)
        tk.Label(
            launch_pad, text="Launch at login", bg=PAPER, fg=INK,
            font=F("serif", 16), anchor="w",
        ).pack(anchor="w")
        self.launch_var = tk.BooleanVar(value=is_launch_at_login_installed())
        self.launch_status_var = tk.StringVar(value="")

        tk.Checkbutton(
            launch_pad, text="Run on login", variable=self.launch_var,
            command=self._toggle_launch_at_login,
            bg=PAPER, fg=INK, font=F("sans", 11),
            activebackground=PAPER, selectcolor=WHITE,
            highlightthickness=0, anchor="w",
        ).pack(anchor="w", pady=(8, 0))
        tk.Label(
            launch_pad, textvariable=self.launch_status_var, bg=PAPER, fg=INK2,
            font=F("sans", 10, "italic"), wraplength=700, justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        self.s_diag_var = tk.StringVar(value="")
        tk.Label(
            s_inner, textvariable=self.s_diag_var, bg=WHITE, fg=INK3,
            font=F("mono", 9), anchor="w", justify="left",
        ).pack(anchor="w", pady=(20, 0))

        self._load_settings_from_config(self.killer.snapshot()["config"])

    def _add_setting_row(self, row, label, var, lo, hi, suffix) -> None:
        tk.Label(
            self.s_grid, text=label, bg=PAPER, fg=INK,
            font=F("sans", 11), anchor="w",
        ).grid(row=row, column=0, sticky="w", pady=10)
        sb = tk.Spinbox(
            self.s_grid, from_=lo, to=hi, textvariable=var, width=6,
            bg=WHITE, fg=INK, font=F("mono", 12),
            relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=LINE,
            buttonbackground=PAPER_ALT,
            command=self._write_settings_from_vars,
        )
        sb.grid(row=row, column=1, sticky="w", padx=18, pady=10)
        tk.Label(
            self.s_grid, text=suffix, bg=PAPER, fg=INK2,
            font=F("sans", 10), anchor="w",
        ).grid(row=row, column=2, sticky="w")
        sb.bind("<FocusOut>", lambda e: self._write_settings_from_vars())
        sb.bind("<Return>", lambda e: self._write_settings_from_vars())
        self.spinboxes.append(sb)

    def _write_settings_from_vars(self) -> None:
        if self._settings_loading:
            return
        snap = self.killer.snapshot()
        cfg = json.loads(json.dumps(snap["config"]))
        try:
            br = max(1, int(self.break_var.get()))
            cd = max(0, int(self.cooldown_var.get()))
            wc = max(1, min(int(self.words_var.get()), len(self.wordlist)))
        except (TypeError, ValueError, tk.TclError):
            return
        cfg.setdefault("settings", {})
        cfg["settings"]["breakDurationMinutes"] = br
        cfg["settings"]["cooldownMinutes"] = cd
        cfg["settings"]["challengeWordCount"] = wc
        save_config(cfg)

    def _load_settings_from_config(self, cfg: dict) -> None:
        s = cfg.get("settings", {}) or {}
        self._settings_loading = True
        try:
            self.break_var.set(int(s.get("breakDurationMinutes", 10)))
            self.cooldown_var.set(int(s.get("cooldownMinutes", 30)))
            self.words_var.set(int(s.get("challengeWordCount", 50)))
        except (TypeError, ValueError):
            pass
        finally:
            self._settings_loading = False

    def _toggle_launch_at_login(self) -> None:
        if self.launch_var.get():
            ok, msg = install_launch_at_login()
            if ok:
                self.launch_status_var.set(f"Installed at: {msg}")
            else:
                self.launch_var.set(False)
                self.launch_status_var.set(f"Failed: {msg}")
        else:
            ok, msg = uninstall_launch_at_login()
            if ok:
                self.launch_status_var.set("Removed.")
            else:
                self.launch_var.set(True)
                self.launch_status_var.set(f"Failed: {msg}")

    # -- background sync + refresh loop -----------------------------------

    def _start_calendar_sync(self) -> None:
        cfg = self.killer.snapshot()["config"]
        cal_cfg = cfg.get("calendar", {})
        additional = cal_cfg.get("additionalCalendars", []) or []
        if not isinstance(additional, list):
            additional = []
        outlook_calendar.start_background_sync(
            interval_seconds=int(cal_cfg.get("syncIntervalSeconds", 60)),
            category=str(cal_cfg.get("deepWorkCategory", "Deep Work")),
            additional_calendars=[str(n) for n in additional if str(n).strip()],
        )

    def _refresh(self) -> None:
        snap = self.killer.snapshot()
        cfg = snap["config"]
        window = snap["active_window"]
        now = datetime.now()
        ends_at = self.killer.break_ends_at()

        self.today_date_var.set(now.strftime("%A, %B %d").upper())

        if ends_at and now < ends_at:
            remaining = (ends_at - now).total_seconds()
            self.pill_var.set("BREAK ACTIVE")
            self.pill_dot.config(bg=OK_GREEN)
            self.pill_label.config(fg=OK_GREEN)
            self.hero_session_var.set("Allowance break")
            self.hero_meta_var.set(f"Ends at {ends_at.strftime('%H:%M')}")
            self.hero_time_var.set(_format_remaining(remaining))
        elif window:
            is_manual = window.get("source") == "manual"
            self.pill_var.set("FOCUS SESSION" if is_manual else "BLOCKING NOW")
            self.pill_dot.config(bg=ACCENT)
            self.pill_label.config(fg=ACCENT)
            self.hero_session_var.set("Focus session" if is_manual else "Deep work")
            try:
                _w_start = datetime.fromisoformat(window["start"]).strftime("%H:%M")
                _w_end = datetime.fromisoformat(window["end"]).strftime("%H:%M")
                self.hero_meta_var.set(f"{_w_start} – {_w_end}")
            except (KeyError, ValueError):
                self.hero_meta_var.set(
                    "Focus session · in progress" if is_manual
                    else "Deep work · in progress"
                )
            try:
                end_dt = datetime.fromisoformat(window["end"])
                # Calendar events arrive tz-aware; `now` is naive. Drop tzinfo
                # so subtraction doesn't raise (same fix pattern as
                # _summarize_calendar_today, see commit e9074c6).
                if end_dt.tzinfo is not None:
                    end_dt = end_dt.replace(tzinfo=None)
                rem = (end_dt - now).total_seconds()
                self.hero_time_var.set(_format_remaining(rem) if rem > 0 else "—")
            except Exception:
                self.hero_time_var.set("—")
        else:
            self.pill_var.set("CLEAR")
            self.pill_dot.config(bg=INK3)
            self.pill_label.config(fg=INK3)
            self.hero_session_var.set("No active block")
            self.hero_meta_var.set(_summarize_calendar_today(now))
            self.hero_time_var.set("—")

        ok, _reason = self.killer.can_take_break()
        self._set_button_enabled(self.break_btn, ok and not ends_at)

        cd_remaining = self.killer.cooldown_remaining_seconds()
        if cd_remaining > 0 and not ends_at:
            self.allowance_caption_var.set(
                f"Allowance available in {_format_remaining(cd_remaining)}")
        else:
            self.allowance_caption_var.set("")

        focus_blocked = bool(window) or bool(ends_at and now < ends_at)
        self._set_button_enabled(self.focus_30_btn, not focus_blocked)
        self._set_button_enabled(self.focus_60_btn, not focus_blocked)

        if window:
            self.sb_label_var.set(
                "Focus session" if window.get("source") == "manual"
                else "Deep work"
            )
            try:
                _sb_end = datetime.fromisoformat(window["end"]).strftime("%H:%M")
                self.sb_sub_var.set(f"ends {_sb_end}")
            except (KeyError, ValueError):
                self.sb_sub_var.set("active")
        else:
            self.sb_label_var.set("None")
            self.sb_sub_var.set(_summarize_calendar_today(now))

        kills = snap["kills"]
        last_tick = snap["last_tick_at"]
        method = snap["method"] or "(none yet)"
        uptime = time.monotonic() - self.started_at
        self.stat_kills_var.set(str(kills))
        self.stat_kills_sub_var.set(f"via {method}")
        if uptime >= 3600:
            self.stat_uptime_var.set(f"{int(uptime // 3600)}h")
        elif uptime >= 60:
            self.stat_uptime_var.set(f"{int(uptime // 60)}m")
        else:
            self.stat_uptime_var.set(f"{int(uptime)}s")
        self.stat_uptime_sub_var.set("uptime")
        cd = self.killer.cooldown_remaining_seconds()
        if ends_at:
            self.stat_cooldown_var.set(_format_remaining(
                (ends_at - now).total_seconds()))
            self.stat_cooldown_sub_var.set("break left")
        elif cd > 0:
            self.stat_cooldown_var.set(_format_remaining(cd))
            self.stat_cooldown_sub_var.set("cooldown")
        elif window:
            self.stat_cooldown_var.set("ready")
            self.stat_cooldown_sub_var.set("eligible")
        else:
            self.stat_cooldown_var.set("—")
            self.stat_cooldown_sub_var.set("no active block")

        last_killed = snap["last_killed"]
        if last_killed:
            self.last_killed_var.set("\n".join(last_killed[-6:]))
        else:
            self.last_killed_var.set("No kills yet.")

        if last_tick == 0:
            self.diag_var.set("Killer thread starting…")
        else:
            ago = max(0.0, time.monotonic() - last_tick)
            self.diag_var.set(
                f"last tick {ago:.1f}s ago · enum {method} · "
                f"uptime {uptime:.0f}s · python "
                f"{sys.version.split()[0]} on "
                f"{platform.system()} {platform.release()}"
            )
        err = snap["config_error"]
        self.err_var.set(f"Config error: {err}" if err else "")
        self.s_diag_var.set(
            f"Wordlist: {len(self.wordlist)} words ({self.wordlist_source})\n"
            f"Config: {config_path()}\n"
            f"State:  {state_path()}"
        )

        self._refresh_apps_list()
        self._refresh_calendar_page()

        locked = self.killer.is_edit_locked()
        edit_remaining = self.killer.edit_unlock_remaining_seconds()
        edit_buttons = (self.apps_add_btn, self.apps_remove_btn)
        if locked:
            if not self.blocks_lock_banner.winfo_ismapped():
                self.blocks_lock_banner.pack(
                    fill=tk.X, pady=(0, 12), before=self.blocks_card)
            for b in edit_buttons:
                self._set_button_enabled(b, False)
        else:
            if self.blocks_lock_banner.winfo_ismapped():
                self.blocks_lock_banner.pack_forget()
            for b in edit_buttons:
                self._set_button_enabled(b, True)
            if edit_remaining > 0:
                rem = (
                    f"Edit access: {_format_remaining(edit_remaining)} "
                    f"remaining"
                )
                self.blocks_lock_label.config(text=rem)
            else:
                self.blocks_lock_label.config(
                    text="List frozen during active block.")

        focused = self.root.focus_get()
        if focused not in self.spinboxes:
            self._load_settings_from_config(cfg)

        self.root.after(500, self._refresh)


def main() -> None:
    MainWindow().run()


if __name__ == "__main__":
    main()
