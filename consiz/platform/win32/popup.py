"""Phase 2 Result Interface for Windows (win32).

Renders a translucent, acrylic/dark glass borderless popup panel next to the mouse cursor.
The window does not steal focus (non-activating), allowing the user's active app to maintain its text selection.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from consiz import history, prefs, voice
from consiz.config import CONFIG
from consiz import dictation as _dictation
from consiz.dictation import AudioRecorder
from consiz.llm import (KIND_TITLES, Cancelled, CancelToken, LLMError, SignInRequired, current_token, take_note,
                        use_token)
from consiz.models import CapturedContext, CaptureMethod, Result
from consiz.output import _pretty_line
from consiz.platform.win32 import dpi
from consiz.platform.win32.theme import (
    CREAM_50,
    CREAM_100,
    CREAM_200,
    CREAM_300,
    MAROON_900,
    MAROON_800,
    MAROON_700,
    MAROON_600,
    INK_MUTED,
    SUCCESS,
    WARNING,
    FOCUS_RING,
    FONT_DISPLAY,
    FONT_TEXT,
)

WIDTH = dpi.px(420)
RECORDING_RED = "#B3261E"         # the microphone button while listening
PAD = 14
RESIZE_BAND = dpi.px(7)           # the strip along each edge of the popup that can be dragged to resize it
SW_SHOWNOACTIVATE = 4
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20
user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

# 64-bit prototypes to prevent handle truncation
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint
]
user32.SetWindowPos.restype = wintypes.BOOL

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long

user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

HWND_TOPMOST = ctypes.cast(-1, wintypes.HWND).value

# Win32 structures for Acrylic blur
class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ('AccentState', ctypes.c_int),
        ('AccentFlags', ctypes.c_int),
        ('GradientColor', ctypes.c_int),
        ('AnimationId', ctypes.c_int)
    ]

class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ('Attribute', ctypes.c_int),
        ('Data', ctypes.POINTER(ACCENT_POLICY)),
        ('SizeOfData', ctypes.c_size_t)
    ]

class MARGINS(ctypes.Structure):
    _fields_ = [
        ('cxLeftWidth', ctypes.c_int),
        ('cxRightWidth', ctypes.c_int),
        ('cyTopHeight', ctypes.c_int),
        ('cyBottomHeight', ctypes.c_int)
    ]


_ROOT: tk.Tk | None = None
_UI_QUEUE: queue.Queue = queue.Queue()


def _get_root() -> tk.Tk:
    global _ROOT
    if _ROOT is None:
        _ROOT = tk.Tk()
        _ROOT.withdraw()

        def _tk_error(exc, val, tb):               # errors inside button/key handlers: log them, keep running
            from consiz import logs
            logs.get().error("Tk callback failed: %s", getattr(exc, "__name__", exc), exc_info=(exc, val, tb))
        _ROOT.report_callback_exception = _tk_error
        # Poll UI queue on main loop
        def poll_queue():
            while not _UI_QUEUE.empty():
                try:
                    fn, args = _UI_QUEUE.get_nowait()
                    fn(*args)
                except Exception:
                    from consiz import logs
                    logs.exception("UI callback")
            if _ROOT:
                _ROOT.after(25, poll_queue)
        _ROOT.after(25, poll_queue)
    return _ROOT


def _dispatch(fn: Callable, *args) -> None:
    _UI_QUEUE.put((fn, args))


def _apply_acrylic(window: tk.Toplevel, is_dark: bool = False) -> None:
    # Per consiz-cream-maroon-ui-redesign.md: "Avoid glassmorphism.
    # Transform the existing dark answer popup into a compact warm-paper panel."
    # DWM blur extension makes light-colored Tkinter windows transparent and washes out ClearType text.
    pass


def _get_cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


class PopupUI:
    """Windows borderless glass popup UI matching macOS HUD panel behavior."""

    def __init__(self, light: bool = False):
        self.light = light
        self.on_ask: Callable[[str], None] | None = None
        self.on_dictate: Callable[[CapturedContext, str], None] | None = None
        self.on_auth_needed: Callable[[], None] | None = None
        self.context = ""
        self.mode = "selection"                # "selection" (explain what I picked) or "pc" (ask about my PC)
        self.last_answer = ""
        self.history: list[dict] = []          # follow-up turns: [{"role","content"}, ...]
        self._msg_texts: list[str] = []        # plain text per assistant message (for per-message Copy)
        self._bubbles: list[tk.Label] = []     # the user's speech bubbles: they re-wrap when the window is resized
        self._transcript: list[list[str]] = []  # [who, text] in order (for Copy all)
        self._ai_open = False
        self._ai_text: list[str] = []
        self._thinking = False
        self._chat_busy = False
        self._token: CancelToken | None = None   # the request in flight; Stop / close / new chat cancel it
        self._action_n = 0
        self._minimized = False
        self._pc_note = ""
        self._saved_h = 0
        self._placeholder_on = True
        self.window: tk.Toplevel | None = None
        self._lines: list[str] = []
        self.user_size: tuple[int, int] | None = _load_size()     # remembered from the last resize (KI-13)
        self._chat_id: str | None = None       # the saved-chat file this conversation is written to (T-13), once it has one
        self._chat_started = 0.0
        self._resize: tuple | None = None      # a drag in progress: (edges, mouse x, mouse y, window box at the start)
        self._edge_cursor = ""
        self._start_x = 0
        self._start_y = 0
        self._recorder = AudioRecorder(
            sample_rate=CONFIG.dictate_sample_rate,
            silence_threshold=CONFIG.dictate_silence_threshold,
            silence_duration_s=CONFIG.dictate_silence_duration_s,
            max_duration_s=CONFIG.dictate_max_duration_s,
        )
        self._is_dictating = False
        self._voice_target = "instruction"     # what a finished recording becomes: "instruction" on the selection, or a chat "question"
        self.on_confirm_action: Callable[[str, str], bool] | None = None    # set by main: the Yes/No box for CHANGE actions (T-12)
        self.on_voice_prepare: Callable[[], bool] | None = None     # set by main: asks to download the speech model if needed
        self._captured_ctx: CapturedContext | None = None
        self.dictate_btn: tk.Label | None = None
        self.mic_btn: tk.Label | None = None

    # ------------------------------------------------------------------ chat UI
    def _build(self) -> None:
        root = _get_root()
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)

        bg_color = CREAM_100
        card_bg = CREAM_50
        sub_color = INK_MUTED
        border_color = CREAM_300
        win.configure(bg=border_color)

        container = tk.Frame(win, bg=bg_color, padx=PAD, pady=PAD - 4)
        container.pack(fill="both", expand=True, padx=1, pady=1)

        accent_bar = tk.Frame(container, bg=MAROON_700, height=2)
        accent_bar.pack(fill="x", side="top", pady=(0, 6))

        # ---- header: title, New chat, close
        header = tk.Frame(container, bg=bg_color)
        header.pack(fill="x", side="top")
        title_lbl = tk.Label(header, text="Consiz", font=(FONT_DISPLAY, 11, "bold"), fg=MAROON_900,
                             bg=bg_color, anchor="w")
        title_lbl.pack(side="left", fill="x", expand=True)

        close_btn = tk.Label(header, text="✕", font=(FONT_TEXT, 10), fg=sub_color, bg=bg_color, cursor="hand2")
        close_btn.pack(side="right", padx=(8, 0))
        close_btn.bind("<Button-1>", lambda e: self.hide())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg=MAROON_700))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=INK_MUTED))

        min_btn = tk.Label(header, text="—", font=(FONT_TEXT, 10, "bold"), fg=sub_color, bg=bg_color, cursor="hand2")
        min_btn.pack(side="right", padx=(8, 4))
        min_btn.bind("<Button-1>", lambda e: self.toggle_minimize())
        min_btn.bind("<Enter>", lambda e: min_btn.configure(fg=MAROON_700))
        min_btn.bind("<Leave>", lambda e: min_btn.configure(fg=INK_MUTED))

        new_btn = tk.Label(header, text="↺ New chat", font=(FONT_TEXT, 8, "bold"), fg=MAROON_700, bg=bg_color,
                           cursor="hand2")
        new_btn.pack(side="right")
        new_btn.bind("<Button-1>", lambda e: self.new_chat())
        new_btn.bind("<Enter>", lambda e: new_btn.configure(fg=MAROON_600))
        new_btn.bind("<Leave>", lambda e: new_btn.configure(fg=MAROON_700))

        meta_lbl = tk.Label(container, text="", font=(FONT_TEXT, 8), fg=sub_color, bg=bg_color, anchor="w")
        meta_lbl.pack(fill="x", side="top", pady=(0, 6))

        # ---- bottom first (so the chat log gets the leftover space): input bar + footer
        footer = tk.Frame(container, bg=bg_color)
        footer.pack(fill="x", side="bottom", pady=(6, 0))

        input_row = tk.Frame(container, bg=bg_color)
        input_row.pack(fill="x", side="bottom", pady=(8, 0))

        send_btn = tk.Label(input_row, text="Send ➤", font=(FONT_TEXT, 9, "bold"), fg=CREAM_50, bg=MAROON_700,
                            padx=12, pady=7, cursor="hand2")
        send_btn.pack(side="right", padx=(6, 0), fill="y")
        send_btn.bind("<Button-1>", lambda e: self._send_or_stop())
        send_btn.bind("<Enter>", lambda e: send_btn.config(bg=MAROON_600 if not self._chat_busy else MAROON_800))
        send_btn.bind("<Leave>", lambda e: send_btn.config(bg=MAROON_700 if not self._chat_busy else MAROON_900))

        mic_btn = tk.Label(input_row, text="🎙", font=(FONT_TEXT, 11), fg=MAROON_800, bg=CREAM_200, padx=10, pady=5,
                           cursor="hand2")
        mic_btn.bind("<Button-1>", lambda e: self._mic_click())
        self.mic_btn = mic_btn

        entry = tk.Text(input_row, font=(FONT_TEXT, 10), fg=MAROON_900, bg=card_bg, insertbackground=MAROON_900,
                        relief="flat", height=1, wrap="word", padx=8, pady=6, highlightthickness=1,
                        highlightbackground=border_color, highlightcolor=FOCUS_RING, undo=True)
        entry.pack(side="left", fill="x", expand=True)

        # ---- chat log (a read-only Text: selectable, streams in place, scrolls)
        log_frame = tk.Frame(container, bg=card_bg, highlightbackground=CREAM_300, highlightthickness=1)
        log_frame.pack(fill="both", expand=True, side="top")
        chat = tk.Text(log_frame, font=(FONT_TEXT, 10), fg=MAROON_900, bg=card_bg, selectbackground=CREAM_300,
                       selectforeground=MAROON_900, wrap="word", relief="flat", padx=10, pady=8, height=6,
                       highlightthickness=0, cursor="arrow", spacing1=1, spacing3=1)
        scrollbar = tk.Scrollbar(log_frame, orient="vertical", command=chat.yview)
        scrollbar.pack(side="right", fill="y")
        chat.config(yscrollcommand=scrollbar.set)
        chat.pack(side="left", fill="both", expand=True)
        chat.bind("<MouseWheel>", lambda e: chat.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        chat.bind("<Configure>", lambda e: self._rewrap_bubbles(e.width))

        chat.tag_configure("who_ai", font=(FONT_TEXT, 8, "bold"), foreground=INK_MUTED, spacing1=8)
        chat.tag_configure("who_user", font=(FONT_TEXT, 8, "bold"), foreground=INK_MUTED, justify="right",
                           spacing1=10, rmargin=4)
        chat.tag_configure("ai", foreground=MAROON_900, lmargin1=4, lmargin2=18, rmargin=24)
        chat.tag_configure("ai_dim", foreground=INK_MUTED, lmargin1=4, lmargin2=18, rmargin=24)
        chat.tag_configure("user_row", justify="right", rmargin=2)
        chat.tag_configure("warn", foreground=WARNING, lmargin1=4, lmargin2=18)
        chat.tag_configure("thinking", foreground=INK_MUTED, font=(FONT_TEXT, 9, "italic"), lmargin1=4)
        chat.tag_configure("chip", foreground=MAROON_700, font=(FONT_TEXT, 10, "bold"), lmargin1=8, lmargin2=22,
                           spacing1=3)
        chat.tag_bind("chip", "<Enter>", lambda e: chat.config(cursor="hand2"))
        chat.tag_bind("chip", "<Leave>", lambda e: chat.config(cursor="arrow"))
        chat.tag_configure("action", foreground=CREAM_50, background=MAROON_700, font=(FONT_TEXT, 10, "bold"),
                           lmargin1=8, spacing1=4, spacing3=2)
        chat.tag_bind("action", "<Enter>", lambda e: chat.config(cursor="hand2"))
        chat.tag_bind("action", "<Leave>", lambda e: chat.config(cursor="arrow"))
        chat.tag_configure("copylink", font=(FONT_TEXT, 8, "bold"), foreground=MAROON_700)
        chat.tag_bind("copylink", "<Enter>", lambda e: chat.config(cursor="hand2"))
        chat.tag_bind("copylink", "<Leave>", lambda e: chat.config(cursor="arrow"))
        chat.config(state="disabled")

        # ---- input behaviour: Enter sends, Shift+Enter = new line, placeholder, grows to 4 lines
        def _focus_in(e):
            self._activate()
            if self._placeholder_on:
                entry.delete("1.0", "end")
                entry.config(fg=MAROON_900)
                self._placeholder_on = False

        def _focus_out(e):
            if not entry.get("1.0", "end-1c").strip():
                self._set_placeholder()

        def _enter(e):
            if e.state & 0x0001:            # Shift held → newline
                return None
            self._submit()
            return "break"

        def _grow_input(e=None):
            lines = int(entry.index("end-1c").split(".")[0])
            entry.config(height=min(4, max(1, lines)))

        entry.bind("<FocusIn>", _focus_in)
        entry.bind("<FocusOut>", _focus_out)
        entry.bind("<Button-1>", lambda e: self._activate())
        entry.bind("<Return>", _enter)
        entry.bind("<KeyRelease>", _grow_input)

        # ---- footer: resize grip + Copy all
        copy_btn = tk.Label(footer, text="Copy all", font=(FONT_TEXT, 8, "bold"), fg=MAROON_800, bg=bg_color,
                            cursor="hand2")
        copy_btn.pack(side="left")
        save_btn = tk.Label(footer, text="Save as text", font=(FONT_TEXT, 8, "bold"), fg=MAROON_800, bg=bg_color,
                            cursor="hand2")
        save_btn.pack(side="left", padx=(14, 0))
        save_btn.bind("<Button-1>", lambda e: self._export_text())
        save_btn.bind("<Enter>", lambda e: save_btn.config(fg=MAROON_600))
        save_btn.bind("<Leave>", lambda e: save_btn.config(fg=MAROON_800))

        def on_copy(e):
            root.clipboard_clear()
            root.clipboard_append(self.full_text())
            copy_btn.config(text="Copied ✓")
            root.after(1500, lambda: copy_btn.config(text="Copy all"))

        copy_btn.bind("<Button-1>", on_copy)
        copy_btn.bind("<Enter>", lambda e: copy_btn.config(fg=MAROON_600))
        copy_btn.bind("<Leave>", lambda e: copy_btn.config(fg=MAROON_800))

        grip = tk.Label(footer, text="◢", font=(FONT_TEXT, 11), fg=MAROON_600, bg=bg_color, cursor="size_nw_se",
                        padx=2)
        grip.pack(side="right")
        grip.bind("<Button-1>", lambda e: self._resize_begin(e, "rb"))

        # every edge and corner of the window resizes it (the window has no frame of its own). The toplevel is in the
        # bindtags of every child, so these see the mouse anywhere; only the plain padding at the border reacts.
        win.bind("<Motion>", self._resize_hover, add="+")
        win.bind("<Button-1>", self._resize_press, add="+")
        win.bind("<B1-Motion>", self._resize_move, add="+")
        win.bind("<ButtonRelease-1>", lambda e: self._resize_end(), add="+")

        # drag the window by its title
        def start_drag(e):
            self._drag_x, self._drag_y = e.x, e.y

        def do_drag(e):
            win.geometry(f"+{win.winfo_x() + e.x - self._drag_x}+{win.winfo_y() + e.y - self._drag_y}")

        for w in (title_lbl, meta_lbl):
            w.bind("<Button-1>", start_drag)
            w.bind("<B1-Motion>", do_drag)

        win.bind("<Escape>", lambda e: self.hide())

        self.window = win
        self.min_btn = min_btn
        self._body_parts = [
            (meta_lbl, dict(fill="x", side="top", pady=(0, 6))),
            (footer, dict(fill="x", side="bottom", pady=(6, 0))),
            (input_row, dict(fill="x", side="bottom", pady=(8, 0))),
            (log_frame, dict(fill="both", expand=True, side="top")),
        ]
        self.title_lbl, self.meta_lbl, self.chat = title_lbl, meta_lbl, chat
        self.text_widget = chat              # kept for older call sites
        self.entry, self.send_btn, self.copy_btn = entry, send_btn, copy_btn
        self._set_placeholder()
        self._noactivate(True)

    # -- focus handling: the popup must NOT steal focus on show (the user's text selection lives in
    #    another app), but it must accept typing once the user clicks into the input.
    def _hwnd(self) -> int:
        return ctypes.windll.user32.GetParent(self.window.winfo_id()) or self.window.winfo_id()

    def _noactivate(self, on: bool) -> None:
        try:
            hwnd = self._hwnd()
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (ex | WS_EX_NOACTIVATE) if on else (ex & ~WS_EX_NOACTIVATE))
        except Exception:
            pass

    def _activate(self) -> None:
        self._noactivate(False)
        try:
            user32.SetForegroundWindow(self._hwnd())
            self.entry.focus_force()
        except Exception:
            pass

    def _set_placeholder(self, text: str | None = None) -> None:
        self.entry.delete("1.0", "end")
        self.entry.insert("1.0", text or ("Ask about your PC…" if self.mode == "pc" else "Ask a follow-up…"))
        self.entry.config(fg=INK_MUTED, height=1)
        self._placeholder_on = True

    # -- chat log primitives (UI thread only)
    def _log(self, text: str, *tags: str) -> None:
        self.chat.config(state="normal")
        self.chat.insert("end", text, tags)
        self.chat.config(state="disabled")

    def _scroll_end(self) -> None:
        self.chat.see("end")

    def _live(self, text: str) -> None:
        """Show the line the AI is writing RIGHT NOW (UI thread). It is replaced by the finished line when its end
        arrives, so words appear as they are generated instead of a whole line at a time."""
        self._hide_thinking()
        if not self._ai_open:
            self._begin_ai()
        self.chat.config(state="normal")
        rng = self.chat.tag_ranges("live")
        if rng:
            self.chat.delete(rng[0], rng[1])
        self.chat.insert("end", text, ("ai", "live"))
        self.chat.config(state="disabled")
        self._scroll_end()

    def _clear_live(self) -> str:
        """Remove the half-written line; returns its text."""
        rng = self.chat.tag_ranges("live")
        if not rng:
            return ""
        self.chat.config(state="normal")
        text = self.chat.get(rng[0], rng[1])
        self.chat.delete(rng[0], rng[1])
        self.chat.config(state="disabled")
        return text

    def _clear_chat(self) -> None:
        self.chat.config(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.config(state="disabled")
        self._lines.clear()
        self._bubbles.clear()
        self._ai_open = False
        self._ai_text = []
        self._thinking = False
        self._transcript = []

    def _begin_ai(self) -> None:
        """Start an assistant message: a small 'Consiz' label with its own Copy link."""
        self._ai_open = True
        self._ai_text = []
        idx = len(self._msg_texts)
        self._msg_texts.append("")
        self._transcript.append(["Consiz", ""])
        tag = f"copy{idx}"
        self.chat.config(state="normal")
        if self.chat.get("1.0", "end-1c"):
            self.chat.insert("end", "\n")
        self.chat.insert("end", "Consiz", ("who_ai",))
        self.chat.insert("end", "   Copy", ("who_ai", "copylink", tag))
        self.chat.insert("end", "\n", ("who_ai",))
        self.chat.tag_bind(tag, "<Button-1>", lambda e, i=idx, t=tag: self._copy_msg(i, t))
        self.chat.config(state="disabled")

    def _copy_msg(self, idx: int, tag: str) -> None:
        root = _get_root()
        root.clipboard_clear()
        root.clipboard_append(self._msg_texts[idx])
        self.chat.config(state="normal")
        r = self.chat.tag_ranges(tag)
        if r:
            self.chat.delete(r[0], r[1])
            self.chat.insert(r[0], "   Copied ✓", ("who_ai", "copylink", tag))
        self.chat.config(state="disabled")

    def _add_user(self, text: str) -> None:
        """A right-aligned maroon bubble sized to its text (an embedded Label, so it hugs the message)."""
        self.chat.config(state="normal")
        if self.chat.get("1.0", "end-1c"):
            self.chat.insert("end", "\n")
        self.chat.insert("end", "You\n", ("who_user",))
        bubble = tk.Label(self.chat, text=text, font=(FONT_TEXT, 10), fg=CREAM_50, bg=MAROON_700, justify="left",
                          anchor="w", wraplength=max(dpi.px(180), int((self.window.winfo_width() or WIDTH) * 0.68)),
                          padx=11, pady=6)
        self.chat.window_create("end", window=bubble, padx=2, pady=2)
        self._bubbles.append(bubble)
        self.chat.insert("end", "\n")
        self.chat.tag_add("user_row", "end-2c linestart", "end-1c")
        self.chat.config(state="disabled")
        self._transcript.append(["You", text])
        self._ai_open = False
        self._scroll_end()
        self._fit_height()

    def _rewrap_bubbles(self, chat_width: int) -> None:
        """A bubble is as wide as its text up to 68 % of the chat; follow the window when it is resized."""
        wrap = max(dpi.px(180), int(chat_width * 0.68))
        for b in self._bubbles:
            try:
                if int(b.cget("wraplength")) != wrap:
                    b.configure(wraplength=wrap)
            except tk.TclError:
                pass

    def _show_thinking(self) -> None:
        if self._thinking:
            return
        self._thinking = True
        self.chat.config(state="normal")
        self.chat.mark_set("think_start", "end-1c")
        self.chat.mark_gravity("think_start", "left")
        self.chat.insert("end", "\nConsiz is thinking…", ("thinking",))
        self.chat.config(state="disabled")
        self._scroll_end()

    def _hide_thinking(self) -> None:
        if not self._thinking:
            return
        self._thinking = False
        self.chat.config(state="normal")
        self.chat.delete("think_start", "end-1c")
        self.chat.config(state="disabled")

    def _set_chat_busy(self, busy: bool) -> None:
        """While an answer is coming the Send button becomes Stop (T-05)."""
        self._chat_busy = busy
        self.send_btn.config(bg=MAROON_900 if busy else MAROON_700, text="■ Stop" if busy else "Send ➤")

    # ------------------------------------------------------------------ Stop / cancel (T-05)
    def _new_token(self) -> CancelToken:
        """A new request replaces (and cancels) any request still in flight. Safe from any thread."""
        tok = CancelToken()
        old, self._token = self._token, tok
        if old is not None:
            old.cancel()
        return tok

    def _if_live(self, tok: CancelToken | None, fn, args) -> None:
        if tok is None or not tok.cancelled:                # late text from a stopped answer is dropped
            fn(*args)

    def _post(self, tok: CancelToken | None, fn, *args) -> None:
        """Queue fn for the UI thread, unless the request was stopped by then."""
        _dispatch(self._if_live, tok, fn, args)

    def _save_history(self) -> None:
        """Write this conversation to its file when the person chose to keep chats (T-13). Cheap and never raises."""
        try:
            if not history.enabled() or not self._transcript:
                return
            if self._chat_id is None:
                self._chat_id, self._chat_started = history.new_id(), time.time()
            history.save(self._chat_id, self.mode, self.title_lbl.cget("text"), self.meta_lbl.cget("text"),
                         list(self._transcript), self._chat_started)
        except Exception:
            pass

    def _export_text(self) -> None:
        """'Save as text': the chat on screen as a .txt in Documents\\Consiz chats, shown in Explorer."""
        if not any(who == "Consiz" and text for who, text in self._transcript):
            self._set_meta("Nothing to save yet")
            return
        try:
            path = history.export_text(self._transcript, self.title_lbl.cget("text"), self.meta_lbl.cget("text"),
                                       self._chat_started or time.time())
        except OSError as e:
            self._set_meta(f"Could not save ({type(e).__name__})")
            return
        self._set_meta(f"Saved: {path}")
        try:
            subprocess.Popen(["explorer", "/select," + str(path)])
        except OSError:
            pass

    def reopen_chat(self, record: dict, at=None) -> None:
        """Show a saved chat again and let the person carry on (any thread)."""
        _dispatch(self._reopen, record, at or _get_cursor_pos())

    def _reopen(self, record: dict, point) -> None:
        pc = record.get("mode") == "pc"
        self._show_at(point, "Earlier chat", record.get("title", ""))
        self.mode = "pc" if pc else "selection"
        self._set_placeholder()
        self.context = "(an earlier chat, shown above)"
        first = True
        for m in record.get("messages", []):
            text = str(m.get("text", ""))
            if m.get("who") == "You":
                self._add_user(text)
                self.history.append({"role": "user", "content": text})
                continue
            self._begin_ai()
            for line in text.splitlines():
                self._append(line)
            if first and not pc:
                self.last_answer = text                      # the first answer; later turns are the follow-up history
            else:
                self.history.append({"role": "assistant", "content": text})
            first = False
        self._chat_id, self._chat_started = record.get("id"), record.get("started") or time.time()
        self._set_meta(f"Saved chat · {len(record.get('messages', []))} messages")

    def _end_run(self, tok: CancelToken) -> None:
        self._save_history()
        if tok is self._token:
            self._token = None
            self._set_chat_busy(False)

    def cancel_request(self, say: bool = True) -> None:
        """Stop the answer that is streaming now (UI thread): the connection is closed, the server stops, and
        nothing more is written to the chat."""
        tok, self._token = self._token, None
        if tok is None and not self._chat_busy:
            return
        if tok is not None:
            tok.cancel()
        self._hide_thinking()
        partial = self._clear_live()                       # keep the half-written line that was already on screen
        if partial.strip():
            self._append(partial)
        self._set_chat_busy(False)
        if say:
            self._log("\nStopped.\n", "ai_dim")
            self._scroll_end()

    def _send_or_stop(self) -> None:
        if self._chat_busy:
            self.cancel_request()
        else:
            self._submit()

    def _submit(self) -> None:
        if self._chat_busy or self._placeholder_on or self.on_ask is None:
            return
        q = self.entry.get("1.0", "end-1c").strip()
        if not q:
            return
        self.entry.delete("1.0", "end")
        self.entry.config(height=1)
        self._add_user(q)
        self._show_thinking()
        self._set_chat_busy(True)
        tok = self._new_token()
        threading.Thread(target=self._run_ask, args=(q, tok), daemon=True).start()

    def _run_ask(self, q: str, tok: CancelToken) -> None:
        use_token(tok)                                     # every AI call this worker makes can now be stopped
        try:
            self.on_ask(q)
        except Cancelled:
            pass
        except Exception as e:
            if not tok.cancelled:
                _dispatch(self._hide_thinking)
                _dispatch(self._append, f"⚠ {_friendly_error(str(e))}")
        finally:
            _dispatch(self._end_run, tok)

    def new_chat(self) -> None:
        if self.window is None:
            return
        self.cancel_request(say=False)
        if self._is_dictating:
            self._is_dictating = False
            self._recorder.cancel()
            self._set_listening(False)
        self._save_history()
        self._chat_id = None
        self._clear_chat()
        self.history.clear()
        self.last_answer = ""
        self._msg_texts.clear()
        if self.mode == "pc":                              # same screen as when it opened: the starter questions
            self._pc_note = ""
            self._set_title("Ask about my PC")
            self._set_meta("Reads program names, memory use and window titles on this PC")
            self._pc_intro()
            return
        self._set_title("New chat")
        self._set_meta("Ask anything about your selected text")
        self._log("Ask a question about the text you selected, or anything else.", "ai_dim")

    def toggle_minimize(self) -> None:
        """A borderless window has no taskbar button, so minimize = collapse to just the title bar (click again
        to expand). It stays where it is, out of the way, and keeps the whole conversation."""
        if self.window is None:
            return
        self._restore() if self._minimized else self._minimize()

    def _minimize(self) -> None:
        self._saved_h = self.window.winfo_height()
        for part, _opts in self._body_parts:
            part.pack_forget()
        self.window.update_idletasks()
        w, x, y = self.window.winfo_width(), self.window.winfo_x(), self.window.winfo_y()
        self.window.geometry(f"{w}x{self.window.winfo_reqheight() + 4}+{x}+{y}")
        self._minimized = True
        self.min_btn.config(text="▢")

    def _restore(self) -> None:
        for part, opts in self._body_parts:
            part.pack(**opts)
        self._minimized = False
        self.min_btn.config(text="—")
        w, x, y = self.window.winfo_width(), self.window.winfo_x(), self.window.winfo_y()
        _l, top, _r, bottom = self._area()
        h = max(self._saved_h, dpi.px(260))
        y = max(top + 10, min(y, bottom - h - 10))        # never let the restored window run off its monitor
        self.window.geometry(f"{w}x{h}+{x}+{y}")

    def _fit_height(self, _retries: int = 8) -> None:
        """Grow the window to fit what is in the chat (up to 65% of the screen); never shrink, never touch a window the
        user resized. The height is measured from the REAL laid-out text. Measuring before the window has been drawn
        (text added in the same instant the window opens: errors, file/table results, the PC chat's question list)
        used to give a 1-pixel-wide window or one far taller than its content, so it waits for the layout instead."""
        if self.window is None or self.user_size is not None or self._minimized:
            return
        self.window.update_idletasks()
        if self.window.winfo_width() < 100 or self.chat.winfo_width() < 50:          # not drawn yet: try again shortly
            if _retries > 0:
                self.window.after(40, lambda: self._fit_height(_retries - 1))
            return
        try:                                                  # pixel height of ALL the text, bubbles included
            res = self.chat.count("1.0", "end", "update", "ypixels")      # a number, or a 1-tuple, depending on Tk
            content = int(res[0] if isinstance(res, (tuple, list)) else res)
        except Exception:
            content = (len(self._lines) + 2) * dpi.px(19)
        chrome = self.window.winfo_height() - self.chat.winfo_height()   # header, input row, footer, borders
        left, top, right, bottom = self._area()
        want = min(max(chrome + content + dpi.px(26), dpi.px(260)), int((bottom - top) * 0.65))
        if want > self.window.winfo_height():
            x, y, w = self.window.winfo_x(), self.window.winfo_y(), self.window.winfo_width()
            if y + want > bottom - 10:
                y = max(top + 10, bottom - want - 10)
            self.window.geometry(f"{w}x{want}+{x}+{y}")

    # ------------------------------------------------------------------ resizing by dragging an edge or corner
    def _resize_hover(self, e) -> None:
        if self._resize is not None or self.window is None or self._minimized:
            return
        edges = edges_at(e.x_root - self.window.winfo_rootx(), e.y_root - self.window.winfo_rooty(),
                         self.window.winfo_width(), self.window.winfo_height(), RESIZE_BAND)
        cursor = _EDGE_CURSORS.get(edges, "")
        if cursor != self._edge_cursor:
            self._edge_cursor = cursor
            self.window.config(cursor=cursor)

    def _resize_press(self, e) -> None:
        if self._minimized:
            return
        edges = edges_at(e.x_root - self.window.winfo_rootx(), e.y_root - self.window.winfo_rooty(),
                         self.window.winfo_width(), self.window.winfo_height(), RESIZE_BAND)
        if edges:
            self._resize_begin(e, edges)

    def _resize_begin(self, e, edges: str) -> None:
        if self.window is None or self._minimized:
            return
        self._resize = (edges, e.x_root, e.y_root, (self.window.winfo_x(), self.window.winfo_y(),
                                                    self.window.winfo_width(), self.window.winfo_height()))

    def _resize_move(self, e) -> None:
        if self._resize is None or self.window is None:
            return
        edges, x0, y0, box = self._resize
        x, y, w, h = resized_box(box, edges, e.x_root - x0, e.y_root - y0, (dpi.px(320), dpi.px(260)), self._area())
        self.user_size = (w, h)                                   # from now on the window keeps the size the user chose
        self.window.geometry(f"{w}x{h}+{x}+{y}")

    def _resize_end(self) -> None:
        if self._resize is not None:
            self._resize = None
            self._save_size()

    def _save_size(self) -> None:
        """Remember the size the user dragged the window to (stored at 100 % scale, so it survives a scale change)."""
        if self.user_size:
            s = dpi.scale()
            prefs.set("popup_size", [round(self.user_size[0] / s), round(self.user_size[1] / s)])

    def _area(self, point: tuple[int, int] | None = None) -> tuple[int, int, int, int]:
        """Usable area (screen minus taskbar) of the monitor under `point`, or under this window (T-06)."""
        if point is None:
            point = (self.window.winfo_x() + 20, self.window.winfo_y() + 20) if self.window is not None else _get_cursor_pos()
        return dpi.work_area_at(*point)

    def _compute_height(self, area: tuple[int, int, int, int] | None = None) -> int:
        if self.user_size:
            return self.user_size[1]
        left, top, right, bottom = area or dpi.work_area_at(*_get_cursor_pos())
        return min(max(dpi.px(260), dpi.px(200) + len(self._lines) * dpi.px(19)), int((bottom - top) * 0.65))

    def _show_at(self, point: tuple[int, int], title: str, meta: str) -> None:
        if self.window is None:
            self._build()
        elif self._minimized:
            self._restore()                               # a new answer always opens fully

        self._clear_chat()
        self._chat_id = None
        self.history.clear()
        self._msg_texts.clear()
        self.title_lbl.config(text=title)
        self.meta_lbl.config(text=meta)
        self.copy_btn.config(text="Copy all")
        self._set_chat_busy(False)
        self._set_placeholder()

        area = dpi.work_area_at(*point)                    # the monitor the user is looking at, not just the main one
        w = self.user_size[0] if self.user_size else WIDTH
        h = self._compute_height(area)
        w, h = dpi.fit_size((w, h), area)                  # a small laptop screen never gets a window bigger than itself
        x, y = dpi.place_near(point, (w, h), area, gap=dpi.px(15))
        self.window.geometry(f"{w}x{h}+{x}+{y}")

        self._refresh_mic()
        # Show without stealing focus (W-07); typing is enabled only when the user clicks the input.
        self._noactivate(True)
        try:
            hwnd = self._hwnd()
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        except Exception:
            self.window.deiconify()

    def _append(self, line: str, dim: bool = False) -> None:
        self._hide_thinking()
        self._clear_live()                                 # the finished line replaces the half-written one
        if not self._ai_open:
            self._begin_ai()
        self._lines.append(line)
        self._ai_text.append(line)
        self._msg_texts[-1] = "\n".join(self._ai_text)
        self._transcript[-1][1] = self._msg_texts[-1]
        tag = "warn" if line.startswith("⚠") else ("ai_dim" if dim else "ai")
        self.chat.config(state="normal")
        self.chat.insert("end", line + "\n", (tag,))
        self.chat.config(state="disabled")
        self._scroll_end()
        self._fit_height()

    def _set_title(self, title: str) -> None:
        if self.title_lbl:
            self.title_lbl.config(text=title)

    def _set_lines(self, pairs: list[tuple[str, bool]]) -> None:
        self._clear_chat()
        self._msg_texts.clear()
        for line, dim in pairs:
            self._append(line, dim)

    def _set_meta(self, meta: str) -> None:
        if self.meta_lbl:
            self.meta_lbl.config(text=meta)

    def toggle_ask(self) -> None:
        """Kept for compatibility: the input bar is always visible now; this just focuses it."""
        if self.window is not None:
            self._activate()

    # ------------------------------------------------------------------ voice dictation
    # Speech is turned into text ON THIS PC (faster-whisper): the audio is never uploaded. Two ways in:
    #   - the microphone button (or Ctrl+Alt+D with nothing selected): what you say becomes a QUESTION in this chat
    #   - Ctrl+Alt+D with text selected: what you say is an INSTRUCTION for that text ("translate to Gujarati")
    def is_listening(self) -> bool:
        return self._is_dictating

    def _refresh_mic(self) -> None:
        """Show the microphone button only when voice dictation is part of this build and switched on."""
        if self.mic_btn is None:
            return
        show = voice.enabled()
        if show and not self.mic_btn.winfo_ismapped():
            self.mic_btn.pack(side="right", padx=(6, 0), fill="y", after=self.send_btn)
        elif not show and self.mic_btn.winfo_ismapped():
            self.mic_btn.pack_forget()

    def _set_listening(self, on: bool) -> None:
        if self.mic_btn is not None:
            self.mic_btn.config(text="■" if on else "🎙", bg=RECORDING_RED if on else CREAM_200,
                                fg=CREAM_50 if on else MAROON_800)
        if self._placeholder_on:
            self._set_placeholder("Listening… speak, then pause" if on else None)

    def _on_audio_level(self, rms: float) -> None:
        if not self._is_dictating:
            return
        bars = min(12, int(rms * 120))
        meter = "█" * bars + "░" * (12 - bars)
        _dispatch(self._set_meta, f"🎙 Listening [{meter}] · pause when you are done, or press ■")

    def _on_auto_stop(self) -> None:
        if self._is_dictating:
            _dispatch(self.stop_dictation)

    def _mic_click(self) -> None:
        """The microphone button: start listening, or stop now."""
        if self._is_dictating:
            self.stop_dictation()
            return
        if self._chat_busy:
            return
        threading.Thread(target=self._start_mic_worker, name="consiz-mic", daemon=True).start()

    def _start_mic_worker(self) -> None:
        ok = self.on_voice_prepare() if self.on_voice_prepare else True       # may ask once to download the speech model
        if ok:
            _dispatch(self.begin_voice_question)

    def begin_voice_question(self) -> None:
        """Listen; what is said becomes a question in this chat (UI thread)."""
        self._voice_target = "question"
        self._begin_recording()

    def _begin_recording(self) -> None:
        if self._is_dictating:
            return
        try:
            self._recorder.start(on_level=self._on_audio_level, on_auto_stop=self._on_auto_stop)
        except Exception as e:
            self._is_dictating = False
            self._set_listening(False)
            self._set_meta("Microphone problem")
            self._append("⚠ " + _mic_error_text(e))
            return
        self._is_dictating = True
        self._set_listening(True)
        self._set_meta("🎙 Listening… speak, then pause")

    def toggle_dictation(self) -> None:
        if self._is_dictating:
            self.stop_dictation()
        else:
            self.begin_voice_question()

    def start_dictation_flow(self, ctx: CapturedContext, at=None) -> None:
        """Ctrl+Alt+D with text selected (worker thread): listen for what to do with that text."""
        point = at or _get_cursor_pos()
        self._captured_ctx = ctx
        self.context = ctx.raw_content
        self.mode = "selection"
        self._voice_target = "instruction"
        _dispatch(self._show_at, point, "🎙 Voice", "Speak what to do with the selected text")
        _dispatch(self._set_lines, [
            ("- Speak what to do with the selected text, then pause:", False),
            ("  • 'Summarize this in 3 bullets'", True),
            ("  • 'Translate this into Gujarati / Hindi / Spanish'", True),
            ("  • 'Explain what this code does'", True),
            ("  • 'Draft a polite reply'", True),
            ("  • 'Copy to clipboard'", True),
            ("- It stops by itself when you pause (or press Ctrl+Alt+D / ■).", False),
        ])
        _dispatch(self._begin_recording)

    def stop_dictation(self) -> None:
        """Stop listening and turn the speech into text on this PC, then use it (any thread)."""
        if not self._is_dictating:
            return
        self._is_dictating = False
        audio = self._recorder.stop()
        question = self._voice_target == "question"
        _dispatch(self._set_listening, False)
        _dispatch(self._set_meta, "⚡ Understanding what you said…")
        if not question:
            _dispatch(self._set_title, "⚡ Transcribing...")

        def work():
            try:
                res = _dictation.get_dictation_engine().transcribe(audio)   # looked up each time: Settings may have changed the model
            except Exception as e:
                from consiz import logs
                logs.exception("transcribe")
                _dispatch(self._set_meta, "Voice problem")
                _dispatch(self._append, "⚠ Could not turn your speech into text: " + str(e)[:120])
                return
            if not res.text:
                _dispatch(self._set_meta, "Nothing heard")
                if question:
                    _dispatch(self._append, "I did not hear anything. Tap the 🎙 button and try again.", True)
                else:
                    _dispatch(self._set_title, "No Speech Detected")
                    _dispatch(self._set_lines, [
                        ("- No clear speech was detected from your microphone.", False),
                        ("- Press Ctrl+Alt+D again and speak after the sound level moves.", True),
                    ])
                return
            if question:
                _dispatch(self._ask_text, res.text.strip())            # shows what was heard, then answers it
                return
            lang_badge = f"[{res.language_name}] " if res.language != "en" else ""
            clean_text = res.text.strip()
            disp_title = (f"🎙 {lang_badge}\"{clean_text[:30]}...\"" if len(clean_text) > 30
                          else f"🎙 {lang_badge}\"{clean_text}\"")
            _dispatch(self._set_title, disp_title)
            _dispatch(self._set_meta, f"Language: {res.language_name} ({res.language_probability:.0%}) · Processing...")
            if self.on_dictate:
                self.on_dictate(self._captured_ctx, res)
            else:
                from consiz.router import process_dictation
                self.show_result(process_dictation(self._captured_ctx, res))

        threading.Thread(target=work, name="whisper-transcribe-worker", daemon=True).start()

    def hide(self) -> None:
        def _do_hide():
            self.cancel_request(say=False)                 # closing the window stops the answer (and the bill)
            self._save_history()
            if self._is_dictating:
                self._is_dictating = False
                self._recorder.cancel()
                self._set_listening(False)
            if self.window is not None:
                self.window.withdraw()
                self._noactivate(True)

        _dispatch(_do_hide)

    def full_text(self) -> str:
        return "\n\n".join(f"{who}: {text}" for who, text in self._transcript if text)

    # ---------------------------------------------------------- worker-thread API
    def open_pc_chat(self, at=None, note: str = "") -> None:
        """Open an empty chat for "Ask about my PC" (no selection needed) with a few starter questions."""
        point = at or _get_cursor_pos()
        self.mode = "pc"
        self._pc_note = note
        self.context, self.last_answer = "", ""
        _dispatch(self._show_at, point, "Ask about my PC", "Reads program names, memory use and window titles on this PC")
        _dispatch(self._pc_intro)

    _PC_STARTERS = ("What is slowing my PC down?", "What am I working on right now?",
                    "What starts with Windows?", "Is anything using the internet a lot?",
                    "How full is my disk?")

    def _pc_intro(self) -> None:
        if self._pc_note:
            self._log(self._pc_note + chr(10), "ai_dim")
        self._log("Ask me anything about this PC. Tap a question or type your own:" + chr(10), "ai_dim")
        for i, q in enumerate(self._PC_STARTERS):
            tag = f"chip{i}"
            self.chat.config(state="normal")
            self.chat.insert("end", f"  ›  {q}" + chr(10), ("chip", tag))
            self.chat.tag_bind(tag, "<Button-1>", lambda e, text=q: self._ask_text(text))
            self.chat.config(state="disabled")
        self._ai_open = False
        self.window.update_idletasks()
        self._fit_height()                     # show all the starter questions without scrolling
        self._activate()                       # the user asked for this window: let it take the keyboard

    def _ask_text(self, text: str) -> None:
        self.entry.delete("1.0", "end")
        self.entry.insert("1.0", text)
        self._placeholder_on = False
        self._submit()

    def show_result(self, res: Result, at=None):
        point = at or _get_cursor_pos()
        self.mode = "selection"
        self.context = res.source_content or res.body
        tok = self._new_token()                            # Stop / close cancels everything below
        use_token(tok)
        try:
            self._render_result(res, point, tok)
        except Cancelled:
            pass
        finally:
            _dispatch(self._end_run, tok)

    def _render_result(self, res: Result, point, tok: CancelToken) -> None:
        def post(fn, *args):
            self._post(tok, fn, *args)

        t0 = res.started_at or time.perf_counter()

        if res.error:
            _dispatch(self._show_at, point, _error_title(res.title), res.source_app)
            for ln in res.body.splitlines():
                post(self._append, ln)
            return

        deferred = res.content_type.startswith(("FILE", "FOLDER", "CSV_DATA")) and res.stream is not None
        meta_label = res.source_app if (res.source_app and (res.source_app.startswith(("🌐", "📁", "📄", "🗂")) or " · " in res.source_app)) else (f"{res.source_app} · {_type_label(res.content_type)}" if res.source_app else _type_label(res.content_type))
        initial_title = res.title if res.title != "auto" else ("Web Context" if res.source_app.startswith("🌐") else "…")
        _dispatch(self._show_at, point, initial_title, meta_label)

        held: list[tuple[str, bool]] = [(_pretty_line(ln), True) for ln in res.body.splitlines()]
        if deferred:
            post(self._append, "Processing…", True)
        else:
            for ln, dim in held:
                post(self._append, ln, dim)

        collected: list[str] = []
        failed = False
        if res.stream is not None:
            post(self._set_chat_busy, True)                # the Send button becomes Stop while the answer streams
            if res.body and not deferred:
                post(self._append, "")
            if not deferred:
                post(self._show_thinking)                  # something is happening while the first words are being made
            elif res.body:
                held.append(("", False))

            title_done = res.title != "auto"
            buf = ""
            last_live = 0.0

            def emit(line: str):
                if deferred:
                    held.append((line, False))
                else:
                    post(self._append, line)

            try:
                for piece in res.stream:
                    tok.check()
                    collected.append(piece)
                    buf += piece
                    while "\n" in buf:
                        done, buf = buf.split("\n", 1)
                        if not done.strip():
                            continue
                        if not title_done:
                            title_done = True
                            k = done.strip().strip("*`#_ ").upper()
                            if k.startswith("KIND"):
                                kind = k.removeprefix("KIND").strip(":*` _")
                                post(self._set_title, KIND_TITLES.get(kind, "Result"))
                                continue
                            default_title = "Web Context" if res.source_app.startswith("🌐") else "Result"
                            post(self._set_title, default_title)
                        emit(_pretty_line(done))
                    now = time.monotonic()
                    if not deferred and buf.strip() and now - last_live >= LIVE_EVERY_SECONDS:
                        shown = live_preview(buf, hide_kind=not title_done)
                        if shown is not None:
                            last_live = now
                            post(self._live, shown)
                if buf.strip():
                    emit(_pretty_line(buf))
            except Cancelled:
                raise
            except LLMError as e:
                failed = True
                if isinstance(e, SignInRequired):
                    emit("Please sign in again to continue.")
                    self._need_login()
                else:
                    emit(_friendly_error(str(e)))
                    emit(f"({e})")
            finally:
                _close_stream(res.stream)

        text = "".join(collected)
        if text.upper().startswith("KIND"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
        extra = res.on_complete(text) if getattr(res, "on_complete", None) and text and not failed else []
        note = take_note()                                 # e.g. "answered offline because the server was unreachable"
        if note:
            if deferred:
                held.append((note, True))
            else:
                post(self._append, note, True)
        for w in list(res.warnings) + extra:
            if deferred:
                held.append((f"⚠ {w}", True))
            else:
                post(self._append, f"⚠ {w}", True)
        if deferred:
            post(self._set_lines, held)

        self.last_answer = text or res.body
        post(self._set_meta, f"{_type_label(res.content_type)} · {res.source_app} · {time.perf_counter() - t0:.1f}s")

    def _need_login(self) -> None:
        """Sign-in expired or was rejected mid-session: reopen the login window (set by main.py)."""
        if self.on_auth_needed is not None:
            _dispatch(self.on_auth_needed)

    def show_followup(self, question: str, stream) -> None:
        """Stream the answer to a follow-up into the SAME chat window (worker thread)."""
        tok = current_token()                              # set by _run_ask: Stop / close cancels this answer
        collected: list[str] = []
        buf = ""
        first_line = True
        last_live = 0.0

        from consiz import pc_actions, pc_mode
        actions: list = []

        def post(fn, *args):
            self._post(tok, fn, *args)

        def emit(line: str) -> None:
            if self.mode == "pc" and pc_actions.is_action_line(line):
                # The AI may SUGGEST one-click actions; each becomes a button that runs only when clicked.
                if len(actions) < pc_actions.MAX_ACTIONS:
                    act = pc_actions.parse(line, pc_mode.last_windows(), pc_mode.last_startup())
                    if act is not None:
                        actions.append(act)
                        post(self._add_action, act)
                return
            post(self._append, _pretty_line(line))

        try:
            for piece in stream:
                if tok is not None:
                    tok.check()
                collected.append(piece)
                buf += piece
                while "\n" in buf:
                    done, buf = buf.split("\n", 1)
                    if not done.strip():
                        continue
                    if first_line:
                        first_line = False
                        if done.strip().strip("*`#_ ").upper().startswith("KIND"):
                            continue
                    emit(done)
                now = time.monotonic()
                if buf.strip() and now - last_live >= LIVE_EVERY_SECONDS:
                    shown = live_preview(buf, hide_kind=first_line)
                    if shown is not None:
                        last_live = now
                        post(self._live, shown)
            if buf.strip() and not (first_line and buf.strip().strip("*`#_ ").upper().startswith("KIND")):
                emit(buf)
        except Cancelled:
            return                                         # stopped by the user: nothing to show, nothing to remember
        except LLMError as e:
            if isinstance(e, SignInRequired):
                post(self._append, "⚠ Please sign in again to continue.")
                self._need_login()
            else:
                post(self._append, "⚠ " + _friendly_error(str(e)))
                post(self._append, f"({e})", True)
            return
        finally:
            _close_stream(stream)
        text = "".join(collected)
        if text.upper().lstrip("*`#_ ").startswith("KIND"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
        text = "\n".join(ln for ln in text.splitlines() if not pc_actions.is_action_line(ln))
        if not text.strip() and not actions:
            post(self._append, "⚠ The AI sent an empty answer. Try asking again.")
            return
        note = take_note()
        if note:
            post(self._append, note, True)
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": text.strip() or "(suggested an action)"})

    def _add_action(self, action) -> None:
        """A suggested one-click action as a button in the chat. It does nothing until clicked."""
        self._action_n += 1
        tag = f"act{self._action_n}"
        self.chat.config(state="normal")
        self.chat.insert("end", f"  ▶  {action.label}" + chr(10), ("action", tag))
        self.chat.tag_bind(tag, "<Button-1>", lambda e, a=action, t=tag: self._run_action(a, t))
        self.chat.config(state="disabled")
        self._scroll_end()
        self._fit_height()

    def _run_action(self, action, tag: str) -> None:
        self.chat.tag_unbind(tag, "<Button-1>")           # one click = one run
        self._replace_tag_text(tag, f"  …  {action.label}", "ai_dim")

        def work():
            from consiz import pc_actions
            ok, msg = pc_actions.run(action, confirm=self.on_confirm_action)     # a CHANGE action asks first, inside run()
            _dispatch(self._replace_tag_text, tag, f"  {'✓' if ok else '⚠'}  {action.label} — {msg}",
                      "ai_dim" if ok else "warn")

        threading.Thread(target=work, name="consiz-action", daemon=True).start()

    def _replace_tag_text(self, tag: str, new_text: str, style: str) -> None:
        rng = self.chat.tag_ranges(tag)
        if not rng:
            return
        self.chat.config(state="normal")
        start = rng[0]
        self.chat.delete(rng[0], rng[1])
        self.chat.insert(start, new_text + chr(10), (style, tag))
        self.chat.config(state="disabled")


LIVE_EVERY_SECONDS = 0.06          # the line being written is refreshed at most ~16 times a second


def live_preview(partial: str, hide_kind: bool = False) -> str | None:
    """What to show for a line the AI is still writing, or None to show nothing yet. The 'KIND:' header and the
    READ:/ACTION: lines are instructions for the program, not text for a person: they are never previewed."""
    s = partial.strip()
    if len(s) < 2:                                       # a lone '-' or '•' would flicker
        return None
    head = s.strip("*`#_ ").upper()
    if hide_kind and (len(head) < 5 or head.startswith("KIND")):
        return None
    if head.startswith(("ACTION", "READ")) or (len(head) < 6 and ("ACTION".startswith(head) or "READ".startswith(head))):
        return None
    return _pretty_line(partial)


_TYPE_LABELS = {"TEXT_SELECTION": "Selected text", "QUESTION": "Question", "FILE": "File", "FOLDER": "Folder",
                "CSV_DATA": "Table", "UNSUPPORTED": "Unsupported", "ACTION": "Done"}
_ERROR_TITLES = {"NO_CONTEXT_FOUND": "Nothing selected", "AMBIGUOUS_SELECTION": "Unclear selection",
                 "UNSUPPORTED_CONTENT": "Can't read this", "DATA_MALFORMED": "Can't read this table",
                 "PROCESSING_TIMEOUT": "Took too long", "SENSITIVE_CONTENT_BLOCKED": "Not sent: looks private",
                 "BACKEND_UNAVAILABLE": "AI not reachable"}


def _type_label(content_type: str) -> str:
    """'TEXT_SELECTION' -> 'Selected text' (people should not see internal names). Unknown values pass through."""
    return _TYPE_LABELS.get(content_type, content_type)


def _error_title(title: str) -> str:
    return _ERROR_TITLES.get(str(title), title)


_EDGE_CURSORS = {"l": "size_we", "r": "size_we", "t": "size_ns", "b": "size_ns",
                 "lt": "size_nw_se", "rb": "size_nw_se", "rt": "size_ne_sw", "lb": "size_ne_sw"}


def edges_at(x: int, y: int, w: int, h: int, band: int) -> str:
    """Which edges of a w x h window the point (x, y), measured from its top-left corner, touches: 'l', 'r', 't', 'b'
    (horizontal one first, so a corner is 'lt', 'rt', 'lb' or 'rb'); '' when the point is well inside."""
    edges = "l" if x < band else "r" if x >= w - band else ""
    return edges + ("t" if y < band else "b" if y >= h - band else "")


def resized_box(box: tuple[int, int, int, int], edges: str, dx: int, dy: int, min_size: tuple[int, int],
                area: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """The (x, y, w, h) of a window after its `edges` were dragged by (dx, dy): never smaller than min_size, never past
    the edge of the usable screen `area`, and the edge opposite to the one being dragged stays where it is."""
    area_l, area_t, area_r, area_b = area
    x, y, w, h = box
    right, bottom = x + w, y + h
    if "r" in edges:
        right = min(right + dx, max(area_r, right))
    if "l" in edges:
        x = max(x + dx, min(area_l, x))
    if "b" in edges:
        bottom = min(bottom + dy, max(area_b, bottom))
    if "t" in edges:
        y = max(y + dy, min(area_t, y))
    min_w, min_h = min(min_size[0], area_r - area_l), min(min_size[1], area_b - area_t)
    if right - x < min_w:
        x, right = (right - min_w, right) if "l" in edges else (x, x + min_w)
    if bottom - y < min_h:
        y, bottom = (bottom - min_h, bottom) if "t" in edges else (y, y + min_h)
    return x, y, right - x, bottom - y


def _load_size() -> tuple[int, int] | None:
    """The saved answer-window size, converted for this screen; None = use the default."""
    raw = prefs.get("popup_size")
    try:
        w, h = int(raw[0]), int(raw[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return dpi.px(min(max(w, 320), 2400)), dpi.px(min(max(h, 260), 1600))


def _close_stream(stream) -> None:
    """Close a generator early so its HTTP connection is released at once."""
    close = getattr(stream, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _mic_error_text(e: Exception) -> str:
    return (f"Could not start the microphone ({str(e)[:100]}). Check that a microphone is connected and that Windows "
            "allows desktop apps to use it: Settings > Privacy & security > Microphone.")


def _friendly_error(detail: str) -> str:
    from consiz.config import CONFIG
    d = detail.lower()
    if "no longer supported" in d:
        return "Please update Consiz: this version is no longer supported."
    if "401" in d or "api key" in d or "insufficient credits" in d or "402" in d:
        return "It's not you, it's the AI. (key problem — check the .env file)"
    if "429" in d or "rate limit" in d:
        return "It's not you, it's the AI. (too many requests — try again in a minute)"
    if "timeout" in d or "timed out" in d:
        if getattr(CONFIG, "provider", "") == "ollama":
            return "It's not you, it's the AI. (local model timed out — 8B+ models can be slow on 4GB GPUs; try a smaller model like llama3.2)"
        return "It's not you, it's the AI. (request timed out — server is busy, please retry)"
    if getattr(CONFIG, "provider", "") == "ollama":
        return f"It's not you, it's the AI. (local Ollama error: {detail})"
    return "It's not you, it's the AI. (couldn't reach the model — check internet and retry)"


def run_app_loop():
    """Starts the GUI main event loop."""
    root = _get_root()

    def _heartbeat():
        if _ROOT:
            _ROOT.after(200, _heartbeat)

    _ROOT.after(200, _heartbeat)
    root.mainloop()
