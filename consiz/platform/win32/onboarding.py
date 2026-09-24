"""First-run onboarding window for Consiz (Win32) — Cream & Maroon Redesign.

Restyled according to consiz-cream-maroon-ui-redesign.md:
- Warm paper-like surfaces (CREAM_100 / CREAM_50 / CREAM_200 / CREAM_300)
- Deep editorial wine typography (MAROON_900 / MAROON_800 / MAROON_700 / MAROON_600)
- 4-segment subtle progress rail
- Styled controls (buttons, inputs, OptionMenu dropdowns, radio buttons)
- Preserves all existing functionality, copy, steps, and options.
"""
from __future__ import annotations

import threading
import tkinter as tk

from consiz.config import CONFIG, save_profile_basics, set_openrouter_key
from consiz.platform.win32.popup import _dispatch, _get_root
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

WIDTH, HEIGHT = 490, 500
PAD = 24

USER_TYPES = ["Student", "CA / Accountant / Finance", "Business owner", "Working professional", "Other"]
REASONS = [
    "Summarizing text & documents",
    "Answering questions quickly",
    "Organizing / sorting files",
    "Translating between languages",
    "Just exploring",
]


def _heading(parent, text, size=19):
    return tk.Label(
        parent,
        text=text,
        font=(FONT_DISPLAY, size, "bold"),
        fg=MAROON_900,
        bg=CREAM_100,
        anchor="w",
        justify="left",
    )


def _body(parent, text, size=10):
    return tk.Label(
        parent,
        text=text,
        font=(FONT_TEXT, size),
        fg=MAROON_900,
        bg=CREAM_100,
        anchor="w",
        justify="left",
        wraplength=WIDTH - 2 * PAD,
    )


def _sub(parent, text, size=9):
    return tk.Label(
        parent,
        text=text,
        font=(FONT_TEXT, size),
        fg=INK_MUTED,
        bg=CREAM_100,
        anchor="w",
        justify="left",
        wraplength=WIDTH - 2 * PAD,
    )


def _style_option_menu(om: tk.OptionMenu) -> None:
    """Style Tkinter OptionMenu and its dropdown menu in cream/maroon aesthetic."""
    om.configure(
        font=(FONT_TEXT, 9),
        bg=CREAM_50,
        fg=MAROON_900,
        activebackground=CREAM_200,
        activeforeground=MAROON_900,
        relief="flat",
        bd=1,
        highlightbackground=CREAM_300,
        highlightthickness=1,
        padx=10,
        pady=5,
        cursor="hand2",
    )
    menu = om["menu"]
    menu.configure(
        font=(FONT_TEXT, 9),
        bg=CREAM_50,
        fg=MAROON_900,
        activebackground=MAROON_700,
        activeforeground=CREAM_50,
        relief="solid",
        bd=1,
    )


class OnboardingUI:
    def __init__(self):
        self.window: tk.Toplevel | None = None
        self.page = 0
        self.pages: list[tk.Frame] = []
        self.step_lbl: tk.Label | None = None
        self.progress_segments: list[tk.Frame] = []
        self.back_btn: tk.Button | None = None
        self.next_btn: tk.Button | None = None

        # page 1 (about you)
        self.name_var: tk.StringVar | None = None
        self.type_var: tk.StringVar | None = None
        self.reason_var: tk.StringVar | None = None

        # page 2 (choose your AI)
        self.provider_var: tk.StringVar | None = None
        self._key_entry: tk.Entry | None = None
        self.ai_status: tk.Label | None = None
        self.cloud_frame: tk.Frame | None = None
        self.offline_frame: tk.Frame | None = None
        self._on_finish = None

    # ---------------------------------------------------------------- build
    def _build(self) -> None:
        root = _get_root()
        self.name_var = tk.StringVar()
        self.provider_var = tk.StringVar(
            value=CONFIG.provider if CONFIG.provider in ("openrouter", "ollama") else "openrouter"
        )

        win = tk.Toplevel(root)
        win.title("Welcome to Consiz")
        win.configure(bg=CREAM_100)
        win.geometry(f"{WIDTH}x{HEIGHT}")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        self.window = win

        # Top progress area
        top_bar = tk.Frame(win, bg=CREAM_100)
        top_bar.place(x=PAD, y=14, width=WIDTH - 2 * PAD, height=36)

        self.step_lbl = tk.Label(
            top_bar,
            text="STEP 1 OF 4",
            font=(FONT_TEXT, 8, "bold"),
            fg=INK_MUTED,
            bg=CREAM_100,
            anchor="w",
        )
        self.step_lbl.pack(anchor="w")

        # 4-segment progress rail
        rail = tk.Frame(top_bar, bg=CREAM_100)
        rail.pack(fill="x", pady=(6, 0))

        self.progress_segments = []
        for _ in range(4):
            seg = tk.Frame(rail, bg=CREAM_300, height=3)
            seg.pack(side="left", fill="x", expand=True, padx=(0, 4))
            self.progress_segments.append(seg)
        # remove trailing pad on last segment
        self.progress_segments[-1].pack_configure(padx=0)

        # Body area
        body_area = tk.Frame(win, bg=CREAM_100)
        body_area.place(x=PAD, y=56, width=WIDTH - 2 * PAD, height=HEIGHT - 128)

        self.pages = [tk.Frame(body_area, bg=CREAM_100) for _ in range(4)]
        self._build_page0(self.pages[0])
        self._build_page1(self.pages[1])
        self._build_page2(self.pages[2])
        self._build_page3(self.pages[3])

        # Hairline divider above footer
        divider = tk.Frame(win, bg=CREAM_300, height=1)
        divider.place(x=PAD, y=HEIGHT - 64, width=WIDTH - 2 * PAD)

        # Footer actions
        footer = tk.Frame(win, bg=CREAM_100)
        footer.place(x=PAD, y=HEIGHT - 54, width=WIDTH - 2 * PAD, height=40)

        self.back_btn = tk.Button(
            footer,
            text="Back",
            font=(FONT_TEXT, 9, "bold"),
            command=lambda: self.go(self.page - 1),
            bg=CREAM_50,
            fg=MAROON_800,
            activebackground=CREAM_200,
            activeforeground=MAROON_900,
            relief="flat",
            bd=1,
            highlightbackground=CREAM_300,
            highlightthickness=1,
            padx=16,
            pady=6,
            cursor="hand2",
        )
        self.back_btn.pack(side="left")

        self.next_btn = tk.Button(
            footer,
            text="Continue",
            font=(FONT_TEXT, 9, "bold"),
            command=self._on_next,
            bg=MAROON_700,
            fg=CREAM_50,
            activebackground=MAROON_600,
            activeforeground=CREAM_50,
            relief="flat",
            bd=0,
            padx=20,
            pady=6,
            cursor="hand2",
        )
        self.next_btn.pack(side="right")

        # Subtle button hover effects
        def on_next_enter(e):
            if self.next_btn["state"] != "disabled":
                self.next_btn.configure(bg=MAROON_600)

        def on_next_leave(e):
            if self.next_btn["state"] != "disabled":
                self.next_btn.configure(bg=MAROON_700)

        def on_back_enter(e):
            if self.back_btn["state"] != "disabled":
                self.back_btn.configure(bg=CREAM_200)

        def on_back_leave(e):
            if self.back_btn["state"] != "disabled":
                self.back_btn.configure(bg=CREAM_50)

        self.next_btn.bind("<Enter>", on_next_enter)
        self.next_btn.bind("<Leave>", on_next_leave)
        self.back_btn.bind("<Enter>", on_back_enter)
        self.back_btn.bind("<Leave>", on_back_leave)

    def _build_page0(self, f: tk.Frame) -> None:
        _heading(f, "Welcome to Consiz").pack(anchor="w", pady=(0, 10))
        _body(
            f,
            "Consiz is a lightweight, thoughtful assistant living quietly in the background of your Windows PC.\n\n"
            "Select anything on your screen — a sentence, a complex document, code, or a folder — "
            f"then press the middle mouse button (or {CONFIG.hotkey}).\n\n"
            "Consiz explains, answers, or summarizes it immediately next to your cursor. "
            "No window switching, no manual copying.",
        ).pack(anchor="w", fill="x")

        # Decorative visual tip card
        tip_card = tk.Frame(f, bg=CREAM_200, bd=1, relief="solid", highlightbackground=CREAM_300, padx=12, pady=10)
        tip_card.pack(anchor="w", fill="x", pady=(14, 0))

        tk.Label(
            tip_card,
            text=f"✦ Trigger: Middle Mouse Click  ·  or  {CONFIG.hotkey}",
            font=(FONT_TEXT, 9, "bold"),
            fg=MAROON_800,
            bg=CREAM_200,
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            tip_card,
            text="Works across any app (browser, PDF viewer, editor, or Explorer).",
            font=(FONT_TEXT, 8),
            fg=INK_MUTED,
            bg=CREAM_200,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

    def _build_page1(self, f: tk.Frame) -> None:
        _heading(f, "A little about you", size=18).pack(anchor="w", pady=(0, 4))
        _sub(
            f,
            "Consiz uses this to personalize answers and drafts so they sound like you — "
            "never shared with anyone, and skipped entirely for plain factual queries.",
        ).pack(anchor="w", fill="x", pady=(0, 14))

        tk.Label(
            f,
            text="Your name (optional)",
            font=(FONT_TEXT, 9, "bold"),
            fg=MAROON_800,
            bg=CREAM_100,
            anchor="w",
        ).pack(anchor="w")
        name_entry = tk.Entry(
            f,
            textvariable=self.name_var,
            font=(FONT_TEXT, 10),
            fg=MAROON_900,
            bg=CREAM_50,
            insertbackground=MAROON_900,
            relief="flat",
            highlightthickness=1,
            highlightbackground=CREAM_300,
            highlightcolor=FOCUS_RING,
        )
        name_entry.pack(anchor="w", fill="x", ipady=5, pady=(4, 12))

        tk.Label(
            f,
            text="What best describes you?",
            font=(FONT_TEXT, 9, "bold"),
            fg=MAROON_800,
            bg=CREAM_100,
            anchor="w",
        ).pack(anchor="w")
        self.type_var = tk.StringVar(value=USER_TYPES[0])
        type_menu = tk.OptionMenu(f, self.type_var, *USER_TYPES)
        _style_option_menu(type_menu)
        type_menu.pack(anchor="w", fill="x", pady=(4, 12))

        tk.Label(
            f,
            text="Why are you using Consiz?",
            font=(FONT_TEXT, 9, "bold"),
            fg=MAROON_800,
            bg=CREAM_100,
            anchor="w",
        ).pack(anchor="w")
        self.reason_var = tk.StringVar(value=REASONS[0])
        reason_menu = tk.OptionMenu(f, self.reason_var, *REASONS)
        _style_option_menu(reason_menu)
        reason_menu.pack(anchor="w", fill="x", pady=(4, 0))

    def _build_page2(self, f: tk.Frame) -> None:
        _heading(f, "Choose your AI", size=18).pack(anchor="w", pady=(0, 10))

        radios = tk.Frame(f, bg=CREAM_100)
        radios.pack(anchor="w", fill="x")

        tk.Radiobutton(
            radios,
            text="Cloud (OpenRouter) — fast, high intelligence, free models",
            variable=self.provider_var,
            value="openrouter",
            command=self._refresh_ai_state,
            font=(FONT_TEXT, 10),
            fg=MAROON_900,
            bg=CREAM_100,
            selectcolor=CREAM_50,
            activebackground=CREAM_100,
            activeforeground=MAROON_900,
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(2, 4))

        tk.Radiobutton(
            radios,
            text=f"Offline ({CONFIG.ollama_model}) — private, runs locally via Ollama",
            variable=self.provider_var,
            value="ollama",
            command=self._refresh_ai_state,
            font=(FONT_TEXT, 10),
            fg=MAROON_900,
            bg=CREAM_100,
            selectcolor=CREAM_50,
            activebackground=CREAM_100,
            activeforeground=MAROON_900,
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(2, 6))

        # Cloud input card
        self.cloud_frame = tk.Frame(f, bg=CREAM_100)
        row = tk.Frame(self.cloud_frame, bg=CREAM_100)
        row.pack(fill="x", pady=(8, 2))

        self._key_entry = tk.Entry(
            row,
            font=(FONT_TEXT, 9),
            fg=MAROON_900,
            bg=CREAM_50,
            insertbackground=MAROON_900,
            relief="flat",
            highlightthickness=1,
            highlightbackground=CREAM_300,
            highlightcolor=FOCUS_RING,
        )
        self._key_entry.pack(side="left", fill="x", expand=True, ipady=5)

        save_btn = tk.Button(
            row,
            text="Save Key",
            font=(FONT_TEXT, 9, "bold"),
            command=self._save_key,
            bg=CREAM_200,
            fg=MAROON_800,
            activebackground=MAROON_700,
            activeforeground=CREAM_50,
            relief="flat",
            bd=1,
            highlightbackground=CREAM_300,
            padx=12,
            cursor="hand2",
        )
        save_btn.pack(side="left", padx=(8, 0))
        _sub(self.cloud_frame, "Get a free key at: openrouter.ai/keys").pack(anchor="w", pady=(2, 0))

        # Offline card
        self.offline_frame = tk.Frame(
            f, bg=CREAM_200, bd=1, relief="solid", highlightbackground=CREAM_300, padx=12, pady=10
        )
        tk.Label(
            self.offline_frame,
            text=f"Runs on your local Ollama instance ({CONFIG.ollama_model}).",
            font=(FONT_TEXT, 9, "bold"),
            fg=MAROON_800,
            bg=CREAM_200,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            self.offline_frame,
            text=f"To change or pull another model:\n  ollama pull {CONFIG.ollama_model}",
            font=(FONT_TEXT, 8),
            fg=INK_MUTED,
            bg=CREAM_200,
            anchor="w",
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        self.ai_status = tk.Label(
            f,
            text="",
            font=(FONT_TEXT, 9, "bold"),
            fg=INK_MUTED,
            bg=CREAM_100,
            anchor="w",
            justify="left",
            wraplength=WIDTH - 2 * PAD,
        )
        self.ai_status.pack(anchor="w", fill="x", pady=(12, 0))

        _sub(f, "You can change your provider anytime by right-clicking the system tray icon.").pack(
            anchor="w", pady=(16, 0)
        )

    def _build_page3(self, f: tk.Frame) -> None:
        _heading(f, "You're all set!", size=19).pack(anchor="w", pady=(0, 12))
        _body(
            f,
            "Consiz is now running quietly in your Windows system tray.\n\n"
            f"•  Select text or a file, then press middle mouse (or {CONFIG.hotkey}) — Consiz explains, "
            "answers, or summarizes immediately.\n\n"
            "•  Type a follow-up question right in the answer popup and press Enter.\n\n"
            "•  Click Copy on any answer to paste it into your active document.\n\n"
            "•  Right-click the Consiz tray icon anytime for settings, model preferences, and language selection.",
        ).pack(anchor="w", fill="x")

    # ---------------------------------------------------------------- navigation
    def go(self, page: int) -> None:
        page = max(0, min(page, len(self.pages) - 1))
        for p in self.pages:
            p.pack_forget()
        self.pages[page].pack(fill="both", expand=True)
        self.page = page

        # Update step label and progress rail
        self.step_lbl.configure(text=f"STEP {page + 1} OF {len(self.pages)}")
        for idx, seg in enumerate(self.progress_segments):
            if idx < page:
                seg.configure(bg=MAROON_700)   # Completed
            elif idx == page:
                seg.configure(bg=MAROON_600)   # Current
            else:
                seg.configure(bg=CREAM_300)   # Future

        if page == 0:
            self.back_btn.configure(state="disabled", fg=INK_MUTED, bg=CREAM_100, cursor="arrow")
        else:
            self.back_btn.configure(state="normal", fg=MAROON_800, bg=CREAM_50, cursor="hand2")

        self.next_btn.configure(
            text="Get Started" if page == 0 else ("Finish Setup" if page == len(self.pages) - 1 else "Continue")
        )

        if page == 2:
            self._refresh_ai_state()

    def _on_next(self) -> None:
        if self.page == len(self.pages) - 1:
            self.finish()
        else:
            self.go(self.page + 1)

    # ---------------------------------------------------------------- page 2: AI backend
    def _refresh_ai_state(self) -> None:
        provider = self.provider_var.get()
        if provider == "openrouter":
            self.offline_frame.pack_forget()
            self.cloud_frame.pack(fill="x")
            import os

            has_key = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
            self.ai_status.configure(
                text="✓ Key saved — Cloud is ready."
                if has_key
                else "Paste your free OpenRouter key above, then click Save Key.",
                fg=SUCCESS if has_key else INK_MUTED,
            )
        else:
            self.cloud_frame.pack_forget()
            self.offline_frame.pack(fill="x", pady=(6, 0))
            self.ai_status.configure(text="Checking for Ollama…", fg=INK_MUTED)
            threading.Thread(target=self._check_ollama, daemon=True).start()

    def _check_ollama(self) -> None:
        try:
            from consiz.llm import _health_ollama

            ok, msg = _health_ollama()
        except Exception as e:
            ok, msg = False, f"Ollama check failed: {e}"
        _dispatch(self._on_ollama_status, ok, msg)

    def _on_ollama_status(self, ok: bool, msg: str) -> None:
        if self.provider_var.get() != "ollama":
            return
        self.ai_status.configure(text=("✓ " if ok else "⚠ ") + msg, fg=SUCCESS if ok else WARNING)

    def _save_key(self) -> None:
        key = self._key_entry.get().strip()
        if not key:
            self.ai_status.configure(text="⚠ Paste your OpenRouter API key first.", fg=WARNING)
            return
        if not key.startswith("sk-or-"):
            self.ai_status.configure(
                text="⚠ That doesn't look like an OpenRouter key (should start with sk-or-).", fg=WARNING
            )
            return
        set_openrouter_key(key)
        CONFIG.provider = "openrouter"
        self.provider_var.set("openrouter")
        self._key_entry.delete(0, "end")
        self.ai_status.configure(text="✓ Key saved — Cloud is ready!", fg=SUCCESS)

    # ---------------------------------------------------------------- finish
    def finish(self) -> None:
        from consiz import prefs

        name = self.name_var.get()
        utype = self.type_var.get() if self.type_var is not None else ""
        reason = self.reason_var.get() if self.reason_var is not None else ""
        try:
            save_profile_basics(name, utype, reason)
        except OSError:
            pass
        CONFIG.provider = self.provider_var.get()
        prefs.set("provider", CONFIG.provider)
        if CONFIG.provider == "ollama":
            prefs.set("ollama_model", CONFIG.ollama_model)
        prefs.set("onboarding_completed", True)
        self.window.withdraw()
        cb, self._on_finish = self._on_finish, None
        if cb is not None:
            cb()

    # ---------------------------------------------------------------- public
    def show(self, on_finish=None) -> None:
        if self.window is None:
            self._build()
        self._on_finish = on_finish
        self.go(0)
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()


_INSTANCE: OnboardingUI | None = None


def open_onboarding(on_finish=None) -> None:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = OnboardingUI()
    _INSTANCE.show(on_finish=on_finish)
