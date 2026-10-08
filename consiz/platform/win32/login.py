"""Sign-in window (Win32): Continue with Google. Cream & Maroon theme.
Logic lives in consiz/auth.py; this file is only the UI."""
from __future__ import annotations

import tkinter as tk

from consiz import auth
from consiz.platform.win32.dpi import px
from consiz.platform.win32.popup import _dispatch, _get_root
from consiz.platform.win32.theme import (
    CREAM_50, CREAM_100, CREAM_200, CREAM_300,
    MAROON_900, MAROON_600,
    INK_MUTED, SUCCESS, WARNING, FONT_DISPLAY, FONT_TEXT,
)

WIDTH, HEIGHT = px(420), px(230)
PAD = px(28)


class LoginUI:
    def __init__(self):
        self.window: tk.Toplevel | None = None
        self._on_done = None
        self._busy = False

    def _build(self) -> None:
        win = tk.Toplevel(_get_root())
        win.title("Sign in to Conciz")
        win.configure(bg=CREAM_100)
        win.geometry(f"{WIDTH}x{HEIGHT}")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        self.window = win

        body = tk.Frame(win, bg=CREAM_100)
        body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        tk.Label(body, text="Sign in", font=(FONT_DISPLAY, 20, "bold"), fg=MAROON_900, bg=CREAM_100,
                 anchor="w").pack(anchor="w")
        tk.Label(body, text="Sign in once to start using Conciz.", font=(FONT_TEXT, 10), fg=INK_MUTED,
                 bg=CREAM_100, anchor="w").pack(anchor="w", pady=(2, 16))

        self.google_btn = tk.Button(
            body, text="Continue with Google", command=self._google, font=(FONT_TEXT, 10, "bold"),
            relief="flat", bd=0, bg=CREAM_50, fg=MAROON_900, activebackground=CREAM_200,
            activeforeground=MAROON_900, highlightbackground=CREAM_300, highlightthickness=1,
            pady=9, cursor="hand2",
        )
        self.google_btn.pack(fill="x")

        self.status = tk.Label(body, text="", font=(FONT_TEXT, 9), fg=INK_MUTED, bg=CREAM_100,
                               wraplength=WIDTH - 2 * PAD, justify="left", anchor="w")
        self.status.pack(anchor="w", pady=(12, 0))

    def _say(self, text: str, ok: bool = False, err: bool = False) -> None:
        self.status.configure(text=text, fg=SUCCESS if ok else WARNING if err else INK_MUTED)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.google_btn.configure(state="disabled" if busy else "normal")

    def _google(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._say("Finish signing in in your browser…")

        def ok(_session):
            _dispatch(self._set_busy, False)
            _dispatch(self._success)

        def err(msg):
            if msg == "Sign-in was cancelled.":     # an older attempt being replaced; the new one owns the UI
                return
            _dispatch(self._set_busy, False)
            _dispatch(self._say, msg, False, True)

        auth.log("login window: Continue with Google clicked")
        auth.run_async(auth.sign_in_google, ok, err)

    def _success(self) -> None:
        self._say("Signed in ✓", ok=True)
        self.window.withdraw()
        cb, self._on_done = self._on_done, None
        if cb is not None:
            cb()

    def show(self, on_done=None) -> None:
        if self.window is None:
            self._build()
        else:
            auth.cancel_pending()          # an old attempt may still be waiting for a browser that was closed
            self._set_busy(False)
            self._say("")
        auth.log("login window shown")
        self._on_done = on_done
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()


_INSTANCE: LoginUI | None = None


def open_login(on_done=None) -> None:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = LoginUI()
    _INSTANCE.show(on_done=on_done)
