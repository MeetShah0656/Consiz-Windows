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
from consiz.llm import KIND_TITLES, LLMError
from consiz.models import CapturedContext, CaptureMethod, Result
from consiz.output import _pretty_line

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
        # Poll UI queue on main loop
        def poll_queue():
            while not _UI_QUEUE.empty():
                try:
                    fn, args = _UI_QUEUE.get_nowait()
                    fn(*args)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
            if _ROOT:
                _ROOT.after(25, poll_queue)
        _ROOT.after(25, poll_queue)
    return _ROOT


def _dispatch(fn: Callable, *args) -> None:
    _UI_QUEUE.put((fn, args))


def _apply_acrylic(window: tk.Toplevel, is_dark: bool = True) -> None:
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        # Enable DWM Acrylic backdrop if Windows 11
        backdrop_val = ctypes.c_int(3)  # DWMSBT_TRANSIENTWINDOW (Acrylic)
        dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop_val), 4)

        # Extend margins
        margins = MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))

        # Accent policy fallback for Win 10/11
        gradient = 0x66181a1f if is_dark else 0x66f5f5f7
        policy = ACCENT_POLICY(4, 2, gradient, 0)
        data = WINCOMPATTRDATA(19, ctypes.pointer(policy), ctypes.sizeof(policy))
        user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception:
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
        self.answer_ui: PopupUI | None = None
        self.ask_visible = False
        self.context = ""
        self.last_answer = ""
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

    def _build(self) -> None:
        root = _get_root()
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)

        bg_color = "#f4f5f8" if self.light else "#16181d"
        card_bg = "#ffffff" if self.light else "#20232a"
        fg_color = "#111111" if self.light else "#f0f2f5"
        sub_color = "#666666" if self.light else "#9aa0a6"
        border_color = "#d1d5db" if self.light else "#323640"

        win.configure(bg=border_color)
        win.attributes("-alpha", 0.94)

        container = tk.Frame(win, bg=bg_color, padx=PAD, pady=PAD)
        container.pack(fill="both", expand=True, padx=1, pady=1)

        # Header: Title + Meta + Close button
        header = tk.Frame(container, bg=bg_color)
        header.pack(fill="x", side="top", pady=(0, 6))

        title_lbl = tk.Label(header, text="Consiz", font=("Segoe UI Variable Display", 11, "bold"),
                             fg=fg_color, bg=bg_color, anchor="w")
        title_lbl.pack(side="left", fill="x", expand=True)

        close_btn = tk.Label(header, text="✕", font=("Segoe UI", 10), fg=sub_color, bg=bg_color, cursor="hand2")
        close_btn.pack(side="right", padx=(6, 0))
        close_btn.bind("<Button-1>", lambda e: self.hide())

        # Meta label
        meta_lbl = tk.Label(container, text="", font=("Segoe UI", 8), fg=sub_color, bg=bg_color, anchor="w")
        meta_lbl.pack(fill="x", side="top", pady=(0, 6))

        # Body text area
        text_frame = tk.Frame(container, bg=card_bg, highlightthickness=0)
        text_frame.pack(fill="both", expand=True)

        text_widget = tk.Text(
            text_frame,
            font=("Segoe UI", 10),
            fg=fg_color,
            bg=card_bg,
            wrap="word",
            relief="flat",
            padx=8,
            pady=8,
            height=6,
            highlightthickness=0
        )
        scrollbar = tk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        scrollbar.pack(side="right", fill="y")
        text_widget.config(yscrollcommand=scrollbar.set)
        text_widget.pack(side="left", fill="both", expand=True)
        text_widget.config(state="disabled")
        text_widget.bind("<MouseWheel>", lambda e: text_widget.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        # Ask entry row (hidden initially)
        ask_frame = tk.Frame(container, bg=bg_color)
        ask_entry = tk.Entry(ask_frame, font=("Segoe UI", 9), fg=fg_color, bg=card_bg,
                             relief="flat", highlightbackground=border_color, highlightthickness=1)
        ask_entry.pack(fill="x", expand=True, ipady=4, pady=(6, 0))

        def on_ask_submit(e):
            q = ask_entry.get().strip()
            if not q or self.on_ask is None:
                return
            ask_entry.delete(0, "end")
            threading.Thread(target=self.on_ask, args=(q,), daemon=True).start()

        ask_entry.bind("<Return>", on_ask_submit)

        # Footer: Actions (Dictate, Ask, Copy)
        footer = tk.Frame(container, bg=bg_color)
        footer.pack(fill="x", side="bottom", pady=(8, 0))

        copy_btn = tk.Label(footer, text="Copy", font=("Segoe UI", 9), fg=fg_color, bg=card_bg,
                            padx=10, pady=3, cursor="hand2", highlightthickness=1, highlightbackground=border_color)
        copy_btn.pack(side="right", padx=(4, 0))

        def on_copy(e):
            root.clipboard_clear()
            root.clipboard_append(self.full_text())
            copy_btn.config(text="Copied")
            root.after(1500, lambda: copy_btn.config(text="Copy"))

        copy_btn.bind("<Button-1>", on_copy)

        ask_btn = None
        # Dictation UI temporarily hidden from the main popup (not yet part of the
        # shared Mac feature set — see As-Conciz/20-For-Meet-What-Consiz-Does-Today-Plain-Words.md).
        # Backend (consiz/dictation.py, process_dictation, start_dictation_flow/stop_dictation
        # below) is untouched — only this button is not created.
        dictate_btn = None
        if not self.light:
            ask_btn = tk.Label(footer, text="Ask", font=("Segoe UI", 9), fg=fg_color, bg=card_bg,
                               padx=10, pady=3, cursor="hand2", highlightthickness=1, highlightbackground=border_color)
            ask_btn.pack(side="right", padx=(4, 0))
            ask_btn.bind("<Button-1>", lambda e: self.toggle_ask())

        # Resize grip / drag support
        grip = tk.Label(footer, text="⋰", font=("Segoe UI", 9), fg=sub_color, bg=bg_color, cursor="size_nw_se")
        grip.pack(side="left")

        def start_resize(e):
            self._start_x, self._start_y = e.x_root, e.y_root
            self._win_w, self._win_h = win.winfo_width(), win.winfo_height()

        def do_resize(e):
            dx = e.x_root - self._start_x
            dy = e.y_root - self._start_y
            nw = max(300, self._win_w + dx)
            nh = max(160, self._win_h + dy)
            self.user_size = (nw, nh)
            win.geometry(f"{nw}x{nh}")

        grip.bind("<Button-1>", start_resize)
        grip.bind("<B1-Motion>", do_resize)

        # Allow dragging the window from title bar
        def start_drag(e):
            self._drag_x, self._drag_y = e.x, e.y

        def do_drag(e):
            x = win.winfo_x() + (e.x - self._drag_x)
            y = win.winfo_y() + (e.y - self._drag_y)
            win.geometry(f"+{x}+{y}")

        title_lbl.bind("<Button-1>", start_drag)
        title_lbl.bind("<B1-Motion>", do_drag)

        # Esc to close
        win.bind("<Escape>", lambda e: self.hide())

        self.window = win
        self.title_lbl = title_lbl
        self.meta_lbl = meta_lbl
        self.text_widget = text_widget
        self.ask_frame = ask_frame
        self.ask_entry = ask_entry
        self.copy_btn = copy_btn
        self.ask_btn = ask_btn
        self.dictate_btn = dictate_btn

        try:
            win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
            old_ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, old_ex | WS_EX_NOACTIVATE)
        except Exception:
            pass

        _apply_acrylic(win, is_dark=not self.light)

    def _compute_height(self) -> int:
        if self.user_size:
            return self.user_size[1]
        line_count = len(self._lines)
        for l in self._lines:
            if len(l) > 42:
                line_count += len(l) // 42
        sh = self.window.winfo_screenheight() if self.window else 900
        max_h = int(sh * 0.65)
        ask_h = 42 if self.ask_visible else 0
        computed = 120 + max(3, line_count) * 22 + ask_h
        return min(max(computed, 180), max_h)

    def _show_at(self, point: tuple[int, int], title: str, meta: str) -> None:
        if self.window is None:
            self._build()

        self._lines.clear()
        self.text_widget.config(state="normal")
        self.text_widget.delete("1.0", "end")
        self.text_widget.config(state="disabled")

        self.title_lbl.config(text=title)
        self.meta_lbl.config(text=meta)
        self.copy_btn.config(text="Copy")

        px, py = point
        w = self.user_size[0] if self.user_size else WIDTH
        h = self._compute_height()

        # Ensure on screen
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        x = min(max(px + 15, 10), sw - w - 10)
        y = min(max(py + 15, 10), sh - h - 10)

        self.window.geometry(f"{w}x{h}+{x}+{y}")

        # Show without stealing focus (W-07)
        try:
            hwnd = ctypes.windll.user32.GetParent(self.window.winfo_id()) or self.window.winfo_id()
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        except Exception:
            self.window.deiconify()

    def _append(self, line: str, dim: bool = False) -> None:
        self._lines.append(line)
        self.text_widget.config(state="normal")
        prefix = "\n" if self.text_widget.get("1.0", "end-1c") else ""
        self.text_widget.insert("end", prefix + line)
        self.text_widget.see("end")
        self.text_widget.config(state="disabled")

        if self.window and self.user_size is None:
            new_h = self._compute_height()
            cur_h = self.window.winfo_height()
            if new_h > cur_h:
                cur_x = self.window.winfo_x()
                cur_y = self.window.winfo_y()
                w = self.window.winfo_width()
                sh = self.window.winfo_screenheight()
                if cur_y + new_h > sh - 10:
                    cur_y = max(10, sh - new_h - 10)
                self.window.geometry(f"{w}x{new_h}+{cur_x}+{cur_y}")

    def _set_title(self, title: str) -> None:
        if self.title_lbl:
            self.title_lbl.config(text=title)

    def _set_lines(self, pairs: list[tuple[str, bool]]) -> None:
        self._lines.clear()
        self.text_widget.config(state="normal")
        self.text_widget.delete("1.0", "end")
        for line, _ in pairs:
            self._append(line)
        self.text_widget.config(state="disabled")

    def _set_meta(self, meta: str) -> None:
        if self.meta_lbl:
            self.meta_lbl.config(text=meta)

    def toggle_ask(self) -> None:
        if self.ask_frame is None:
            return
        self.ask_visible = not self.ask_visible
        if self.ask_visible:
            self.ask_frame.pack(fill="x", side="top", pady=(0, 6))
            self.window.geometry(f"{self.window.winfo_width()}x{self.window.winfo_height() + 40}")
            self.ask_entry.focus_set()
        else:
            self.ask_frame.pack_forget()
            self.window.geometry(f"{self.window.winfo_width()}x{max(180, self.window.winfo_height() - 40)}")

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
        fg_col = "#111111" if self.light else "#f0f2f5"
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
                if self.dictate_btn:
                    self.dictate_btn.config(text="🎙 Dictate", fg="#111111" if self.light else "#f0f2f5")
            if self.window is not None:
                self.window.withdraw()
            if self.answer_ui is not None:
                self.answer_ui.hide()
            if self.ask_visible:
                self.toggle_ask()

        _dispatch(_do_hide)

    def full_text(self) -> str:
        return "\n".join(self._lines)

    # ---------------------------------------------------------- worker-thread API
    def show_result(self, res: Result, at=None):
        point = at or _get_cursor_pos()
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

    def show_followup(self, question: str, stream) -> None:
        if self.answer_ui is None:
            self.answer_ui = PopupUI(light=True)
        cx, cy = _get_cursor_pos()
        at = (cx + WIDTH + 20, cy)
        res = Result(title="Assistant", content_type=f"you asked: {question[:40]}", source_app="", stream=stream)
        self.answer_ui.show_result(res, at=at)


def _friendly_error(detail: str) -> str:
    d = detail.lower()
    if "401" in d or "api key" in d or "insufficient credits" in d or "402" in d:
        return "It's not you, it's the AI. (key problem — check the .env file)"
    if "429" in d or "rate limit" in d:
        return "It's not you, it's the AI. (too many requests — try again in a minute)"
    return "It's not you, it's the AI. (couldn't reach the model — check internet and retry)"


def run_app_loop():
    """Starts the GUI main event loop."""
    root = _get_root()

    def _heartbeat():
        if _ROOT:
            _ROOT.after(200, _heartbeat)

    _ROOT.after(200, _heartbeat)
    root.mainloop()
