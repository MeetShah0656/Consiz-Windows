"""Phase 2 Result Interface for Windows (win32).

Renders a translucent, acrylic/dark glass borderless popup panel next to the mouse cursor.
The window does not steal focus (non-activating), allowing the user's active app to maintain its text selection.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from consiz.config import CONFIG
from consiz.dictation import AudioRecorder, get_dictation_engine
from consiz.llm import KIND_TITLES, LLMError, SignInRequired
from consiz.models import CapturedContext, CaptureMethod, Result
from consiz.output import _pretty_line
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

WIDTH = 420
PAD = 14
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
        self._transcript: list[list[str]] = []  # [who, text] in order (for Copy all)
        self._ai_open = False
        self._ai_text: list[str] = []
        self._thinking = False
        self._chat_busy = False
        self._action_n = 0
        self._minimized = False
        self._pc_note = ""
        self._saved_h = 0
        self._placeholder_on = True
        self.window: tk.Toplevel | None = None
        self._lines: list[str] = []
        self.user_size: tuple[int, int] | None = None
        self._start_x = 0
        self._start_y = 0
        self._recorder = AudioRecorder(
            sample_rate=CONFIG.dictate_sample_rate,
            silence_threshold=CONFIG.dictate_silence_threshold,
            silence_duration_s=CONFIG.dictate_silence_duration_s,
            max_duration_s=CONFIG.dictate_max_duration_s,
        )
        self._is_dictating = False
        self._captured_ctx: CapturedContext | None = None
        self.dictate_btn: tk.Label | None = None

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
        send_btn.bind("<Button-1>", lambda e: self._submit())
        send_btn.bind("<Enter>", lambda e: send_btn.config(bg=MAROON_600))
        send_btn.bind("<Leave>", lambda e: send_btn.config(bg=MAROON_700 if not self._chat_busy else INK_MUTED))

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
        copy_btn.pack(side="right")

        def on_copy(e):
            root.clipboard_clear()
            root.clipboard_append(self.full_text())
            copy_btn.config(text="Copied ✓")
            root.after(1500, lambda: copy_btn.config(text="Copy all"))

        copy_btn.bind("<Button-1>", on_copy)
        copy_btn.bind("<Enter>", lambda e: copy_btn.config(fg=MAROON_600))
        copy_btn.bind("<Leave>", lambda e: copy_btn.config(fg=MAROON_800))

        grip = tk.Label(footer, text="⋰", font=(FONT_TEXT, 9), fg=sub_color, bg=bg_color, cursor="size_nw_se")
        grip.pack(side="left")

        def start_resize(e):
            self._start_x, self._start_y = e.x_root, e.y_root
            self._win_w, self._win_h = win.winfo_width(), win.winfo_height()

        def do_resize(e):
            nw = max(320, self._win_w + e.x_root - self._start_x)
            nh = max(260, self._win_h + e.y_root - self._start_y)
            self.user_size = (nw, nh)
            win.geometry(f"{nw}x{nh}")

        grip.bind("<Button-1>", start_resize)
        grip.bind("<B1-Motion>", do_resize)

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

    def _set_placeholder(self) -> None:
        self.entry.delete("1.0", "end")
        self.entry.insert("1.0", "Ask about your PC…" if self.mode == "pc" else "Ask a follow-up…")
        self.entry.config(fg=INK_MUTED, height=1)
        self._placeholder_on = True

    # -- chat log primitives (UI thread only)
    def _log(self, text: str, *tags: str) -> None:
        self.chat.config(state="normal")
        self.chat.insert("end", text, tags)
        self.chat.config(state="disabled")

    def _scroll_end(self) -> None:
        self.chat.see("end")

    def _clear_chat(self) -> None:
        self.chat.config(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.config(state="disabled")
        self._lines.clear()
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
                          anchor="w", wraplength=max(180, int((self.window.winfo_width() or WIDTH) * 0.68)),
                          padx=11, pady=6)
        self.chat.window_create("end", window=bubble, padx=2, pady=2)
        self.chat.insert("end", "\n")
        self.chat.tag_add("user_row", "end-2c linestart", "end-1c")
        self.chat.config(state="disabled")
        self._transcript.append(["You", text])
        self._ai_open = False
        self._scroll_end()
        self._fit_height()

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
        self._chat_busy = busy
        self.send_btn.config(bg=INK_MUTED if busy else MAROON_700, text="…" if busy else "Send ➤")

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
        threading.Thread(target=self._run_ask, args=(q,), daemon=True).start()

    def _run_ask(self, q: str) -> None:
        try:
            self.on_ask(q)
        except Exception as e:
            _dispatch(self._hide_thinking)
            _dispatch(self._append, f"⚠ {_friendly_error(str(e))}")
        finally:
            _dispatch(self._set_chat_busy, False)

    def new_chat(self) -> None:
        if self.window is None:
            return
        self._clear_chat()
        self.history.clear()
        self.last_answer = ""
        self._msg_texts.clear()
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
        sh = self.window.winfo_screenheight()
        h = max(self._saved_h, 260)
        y = max(10, min(y, sh - h - 10))                  # never let the restored window run off the screen
        self.window.geometry(f"{w}x{h}+{x}+{y}")

    def _fit_height(self) -> None:
        """Grow the window to fit the conversation (until 65% of the screen); never shrink a user-sized one."""
        if self.window is None or self.user_size is not None or self._minimized:
            return
        try:
            display_lines = self.chat.count("1.0", "end", "displaylines")
            n = int(display_lines[0]) if display_lines else len(self._lines)
        except Exception:
            n = len(self._lines)
        sh = self.window.winfo_screenheight()
        want = min(max(200 + n * 19, 260), int(sh * 0.65))
        cur_h = self.window.winfo_height()
        if want > cur_h:
            x, y, w = self.window.winfo_x(), self.window.winfo_y(), self.window.winfo_width()
            if y + want > sh - 10:
                y = max(10, sh - want - 10)
            self.window.geometry(f"{w}x{want}+{x}+{y}")

    def _compute_height(self) -> int:
        if self.user_size:
            return self.user_size[1]
        sh = self.window.winfo_screenheight() if self.window else 900
        return min(max(260, 200 + len(self._lines) * 19), int(sh * 0.65))

    def _show_at(self, point: tuple[int, int], title: str, meta: str) -> None:
        if self.window is None:
            self._build()
        elif self._minimized:
            self._restore()                               # a new answer always opens fully

        self._clear_chat()
        self.history.clear()
        self._msg_texts.clear()
        self.title_lbl.config(text=title)
        self.meta_lbl.config(text=meta)
        self.copy_btn.config(text="Copy all")
        self._set_chat_busy(False)
        self._set_placeholder()

        px, py = point
        w = self.user_size[0] if self.user_size else WIDTH
        h = self._compute_height()
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        x = min(max(px + 15, 10), sw - w - 10)
        y = min(max(py + 15, 10), sh - h - 10)
        self.window.geometry(f"{w}x{h}+{x}+{y}")

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

    def _on_audio_level(self, rms: float) -> None:
        if not self._is_dictating:
            return
        bars = min(12, int(rms * 120))
        meter = "█" * bars + "░" * (12 - bars)
        _dispatch(self._set_meta, f"🎙 Listening [{meter}] · Click '✓ Done' (or Ctrl+Alt+D) when finished")

    def _on_auto_stop(self) -> None:
        if self._is_dictating:
            _dispatch(self.stop_dictation)

    def toggle_dictation(self) -> None:
        if self._is_dictating:
            self.stop_dictation()
        else:
            ctx = self._captured_ctx or CapturedContext("active", CaptureMethod.TEXT_SELECTION, self.context)
            self.start_dictation_flow(ctx)

    def start_dictation_flow(self, ctx: CapturedContext, at=None) -> None:
        point = at or _get_cursor_pos()
        self._captured_ctx = ctx
        self.context = ctx.raw_content
        self._is_dictating = True

        _dispatch(self._show_at, point, "🎙 Dictate Command", "Listening... click '✓ Done' when finished")
        hints = [
            ("- 🎙 Listening for your voice instruction...", False),
            ("- Speak what you want to do with the selected text:", True),
            ("  • 'Summarize this in 3 bullets'", True),
            ("  • 'Translate this into Gujarati / Spanish / Hindi'", True),
            ("  • 'Explain what this code does'", True),
            ("  • 'Draft a professional email reply'", True),
            ("  • 'Copy to clipboard'", True),
            ("- Click '✓ Done' (or press Ctrl+Alt+D) when you are done speaking.", False),
        ]
        _dispatch(self._set_lines, hints)
        if self.dictate_btn:
            _dispatch(self.dictate_btn.config, {"text": "✓ Done", "fg": "#10b981"})

        try:
            self._recorder.start(on_level=self._on_audio_level, on_auto_stop=self._on_auto_stop)
        except Exception as e:
            self._is_dictating = False
            fg_col = "#111111" if self.light else "#f0f2f5"
            if self.dictate_btn:
                _dispatch(self.dictate_btn.config, {"text": "🎙 Dictate", "fg": fg_col})
            _dispatch(self._set_title, "Microphone Error")
            _dispatch(self._set_meta, "No active audio input device")
            _dispatch(self._set_lines, [
                ("- Could not start recording: " + str(e), False),
                ("- Please connect or enable a microphone in Windows Sound Settings and try again.", True),
            ])
            return

    def stop_dictation(self) -> None:
        if not self._is_dictating:
            return
        self._is_dictating = False
        fg_col = MAROON_800
        if self.dictate_btn:
            _dispatch(self.dictate_btn.config, {"text": "🎙 Dictate", "fg": fg_col})

        audio = self._recorder.stop()
        _dispatch(self._set_title, "⚡ Transcribing...")
        _dispatch(self._set_meta, "faster-whisper transcribing speech to command...")

        def _transcribe_and_run():
            engine = get_dictation_engine()
            res = engine.transcribe(audio)
            if not res.text:
                _dispatch(self._set_title, "No Speech Detected")
                _dispatch(self._set_meta, "Try speaking again or use 'Ask'")
                _dispatch(self._set_lines, [
                    ("- No clear speech was detected from your microphone.", False),
                    ("- Click '🎙 Dictate' or press Ctrl+Alt+D and speak clearly in any language.", True),
                ])
                return

            lang_badge = f"[{res.language_name}] " if res.language != "en" else ""
            clean_text = res.text.strip()
            disp_title = f"🎙 {lang_badge}\"{clean_text[:30]}...\"" if len(clean_text) > 30 else f"🎙 {lang_badge}\"{clean_text}\""
            _dispatch(self._set_title, disp_title)
            _dispatch(self._set_meta, f"Language: {res.language_name} ({res.language_probability:.0%}) · Processing...")

            if self.on_dictate:
                self.on_dictate(self._captured_ctx, res)
            else:
                from consiz.router import process_dictation
                result = process_dictation(self._captured_ctx, res)
                self.show_result(result)

        threading.Thread(target=_transcribe_and_run, name="whisper-transcribe-worker", daemon=True).start()

    def hide(self) -> None:
        def _do_hide():
            if self._is_dictating:
                self._is_dictating = False
                self._recorder.cancel()
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
        t0 = res.started_at or time.perf_counter()

        if res.error:
            _dispatch(self._show_at, point, res.title, res.source_app)
            for ln in res.body.splitlines():
                _dispatch(self._append, ln)
            return

        deferred = res.content_type.startswith(("FILE", "FOLDER", "CSV_DATA")) and res.stream is not None
        meta_label = res.source_app if (res.source_app and (res.source_app.startswith(("🌐", "📁", "📄", "🗂")) or " · " in res.source_app)) else (f"{res.source_app} · {res.content_type}" if res.source_app else res.content_type)
        initial_title = res.title if res.title != "auto" else ("Web Context" if res.source_app.startswith("🌐") else "…")
        _dispatch(self._show_at, point, initial_title, meta_label)

        held: list[tuple[str, bool]] = [(_pretty_line(ln), True) for ln in res.body.splitlines()]
        if deferred:
            _dispatch(self._append, "Processing…", True)
        else:
            for ln, dim in held:
                _dispatch(self._append, ln, dim)

        collected: list[str] = []
        failed = False
        if res.stream is not None:
            if res.body and not deferred:
                _dispatch(self._append, "")
            elif res.body:
                held.append(("", False))

            title_done = res.title != "auto"
            buf = ""

            def emit(line: str):
                if deferred:
                    held.append((line, False))
                else:
                    _dispatch(self._append, line)

            try:
                for piece in res.stream:
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
                                _dispatch(self._set_title, KIND_TITLES.get(kind, "Result"))
                                continue
                            default_title = "Web Context" if res.source_app.startswith("🌐") else "Result"
                            _dispatch(self._set_title, default_title)
                        emit(_pretty_line(done))
                if buf.strip():
                    emit(_pretty_line(buf))
            except LLMError as e:
                failed = True
                if isinstance(e, SignInRequired):
                    emit("Please sign in again to continue.")
                    self._need_login()
                else:
                    emit(_friendly_error(str(e)))
                    emit(f"({e})")

        text = "".join(collected)
        if text.upper().startswith("KIND"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
        extra = res.on_complete(text) if getattr(res, "on_complete", None) and text and not failed else []
        for w in list(res.warnings) + extra:
            if deferred:
                held.append((f"⚠ {w}", True))
            else:
                _dispatch(self._append, f"⚠ {w}", True)
        if deferred:
            _dispatch(self._set_lines, held)

        self.last_answer = text or res.body
        _dispatch(self._set_meta, f"{res.content_type} · {res.source_app} · {time.perf_counter() - t0:.1f}s")

    def _need_login(self) -> None:
        """Sign-in expired or was rejected mid-session: reopen the login window (set by main.py)."""
        if self.on_auth_needed is not None:
            _dispatch(self.on_auth_needed)

    def show_followup(self, question: str, stream) -> None:
        """Stream the answer to a follow-up into the SAME chat window (worker thread)."""
        collected: list[str] = []
        buf = ""
        first_line = True

        from consiz import pc_actions, pc_mode
        actions: list = []

        def emit(line: str) -> None:
            if self.mode == "pc" and pc_actions.is_action_line(line):
                # The AI may SUGGEST one-click actions; each becomes a button that runs only when clicked.
                if len(actions) < pc_actions.MAX_ACTIONS:
                    act = pc_actions.parse(line, pc_mode.last_windows())
                    if act is not None:
                        actions.append(act)
                        _dispatch(self._add_action, act)
                return
            _dispatch(self._append, _pretty_line(line))

        try:
            for piece in stream:
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
            if buf.strip() and not (first_line and buf.strip().strip("*`#_ ").upper().startswith("KIND")):
                emit(buf)
        except LLMError as e:
            if isinstance(e, SignInRequired):
                _dispatch(self._append, "⚠ Please sign in again to continue.")
                self._need_login()
            else:
                _dispatch(self._append, "⚠ " + _friendly_error(str(e)))
                _dispatch(self._append, f"({e})", True)
            return
        text = "".join(collected)
        if text.upper().lstrip("*`#_ ").startswith("KIND"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
        text = "\n".join(ln for ln in text.splitlines() if not pc_actions.is_action_line(ln))
        if not text.strip() and not actions:
            _dispatch(self._append, "⚠ The AI sent an empty answer. Try asking again.")
            return
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
            ok, msg = pc_actions.run(action)
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


def _friendly_error(detail: str) -> str:
    from consiz.config import CONFIG
    d = detail.lower()
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
