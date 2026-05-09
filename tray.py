"""System tray icon (Windows) for the app blocker.

Uses pywin32's Shell_NotifyIcon so the main window can be hidden from the
taskbar while the app keeps running. Left-click restores; right-click shows
a Show / Quit menu.

The tray runs on its own daemon thread with its own GetMessage loop so it
does not interfere with Tk's mainloop. Callbacks fire on the tray thread —
the caller is responsible for marshalling work back to the Tk thread (e.g.
via root.after(0, ...)).
"""

from __future__ import annotations

import threading
from pathlib import Path

_WIN32_IMPORT_ERROR: str | None = None
try:
    import win32api  # type: ignore
    import win32con  # type: ignore
    import win32gui  # type: ignore
    HAVE_WIN32 = True
except ImportError as _e:
    HAVE_WIN32 = False
    _WIN32_IMPORT_ERROR = str(_e)


WM_TRAYICON = 0x0400 + 20  # WM_USER + 20
_CMD_SHOW = 1
_CMD_QUIT = 2


class TrayIcon:
    """Hidden-window-backed Shell_NotifyIcon tray entry.

    Callbacks fire on the tray's worker thread.
    """

    def __init__(self, *, title: str, on_show, on_quit,
                 icon_path: str | Path | None = None) -> None:
        if not HAVE_WIN32:
            raise RuntimeError(f"pywin32 unavailable: {_WIN32_IMPORT_ERROR}")
        self._title = title
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon_path = Path(icon_path) if icon_path else None
        self._hwnd: int | None = None
        self._hicon = None
        self._tray_id = 1
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="TrayIcon", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        if self._hwnd:
            try:
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass

    # ---- internal --------------------------------------------------------

    def _run(self) -> None:
        wc = win32gui.WNDCLASS()
        wc.lpszClassName = "StillwaterAppBlockerTray"
        wc.lpfnWndProc = self._wnd_proc
        wc.hInstance = win32api.GetModuleHandle(None)
        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass  # already registered (e.g. previous run in same interpreter)

        self._hwnd = win32gui.CreateWindow(
            wc.lpszClassName, self._title, 0,
            0, 0, 0, 0, 0, 0, wc.hInstance, None,
        )
        win32gui.UpdateWindow(self._hwnd)

        self._hicon = self._load_icon()
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        nid = (self._hwnd, self._tray_id, flags, WM_TRAYICON,
               self._hicon, self._title)
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

        self._ready.set()
        win32gui.PumpMessages()

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            if lparam == win32con.WM_LBUTTONUP:
                self._safe_call(self._on_show)
            elif lparam == win32con.WM_RBUTTONUP:
                self._show_menu()
        elif msg == win32con.WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == _CMD_SHOW:
                self._safe_call(self._on_show)
            elif cmd == _CMD_QUIT:
                self._safe_call(self._on_quit)
        elif msg == win32con.WM_CLOSE:
            win32gui.DestroyWindow(hwnd)
            return 0
        elif msg == win32con.WM_DESTROY:
            try:
                win32gui.Shell_NotifyIcon(
                    win32gui.NIM_DELETE, (self._hwnd, self._tray_id)
                )
            except Exception:
                pass
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _load_icon(self):
        if self._icon_path and self._icon_path.is_file():
            try:
                cx = win32api.GetSystemMetrics(win32con.SM_CXSMICON)
                cy = win32api.GetSystemMetrics(win32con.SM_CYSMICON)
                return win32gui.LoadImage(
                    0, str(self._icon_path), win32con.IMAGE_ICON,
                    cx, cy, win32con.LR_LOADFROMFILE,
                )
            except Exception:
                pass
        return win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

    def _show_menu(self) -> None:
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, _CMD_SHOW, "Show")
        win32gui.AppendMenu(menu, win32con.MF_STRING, _CMD_QUIT, "Quit")
        x, y = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self._hwnd)
        win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON,
            x, y, 0, self._hwnd, None,
        )
        # Per MSDN: post a benign message so the menu dismisses cleanly when
        # the user clicks elsewhere.
        win32gui.PostMessage(self._hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(menu)

    @staticmethod
    def _safe_call(fn) -> None:
        try:
            fn()
        except Exception:
            pass
