"""First-run onboarding: a real (titled) window, separate from the small glass answer popup, shown
exactly once per install. Four pages in one window (Back/Next, no new windows per step), mirroring the
macOS onboarding flow (consiz/platform/darwin/onboarding.py) with Windows-native widgets and copy:

  1. Welcome        — what Consiz is, in plain words (Windows shortcuts: middle mouse / Ctrl+Alt+S).
  2. About you       — name, what kind of user, why they're here. Saved into profile.md via
                       config.save_profile_basics(), the same personalization file llm.py already reads.
  3. Choose your AI  — Cloud (OpenRouter) or Offline (Ollama). This is currently the ONLY place on
                       Windows to set the AI backend — there is no Settings window yet (doc 20 §4 lists
                       it as still to build) — so, unlike macOS, this step is load-bearing, not optional
                       polish. Offline only reports whether Ollama is already installed/running; the
                       one-click "download the model for me" flow macOS has (consiz/offline_model.py)
                       has not been ported, so Offline shows manual install/pull instructions instead.
                       No Enterprise/M365 option — that backend does not exist on Windows at all yet.
  4. All set         — what you can do right now, using only what Windows actually has today (no Sort,
                       no Dictate — see As-Conciz/20-For-Meet-What-Consiz-Does-Today-Plain-Words.md).

Shown once: gated by prefs.get("onboarding_completed") in main.py, set True when page 4's button is
clicked. Closing the window early (the OS close button) leaves the flag unset, so it simply reappears
next launch — same as never having finished it.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import font as tkfont

from consiz.config import CONFIG, save_profile_basics, set_openrouter_key
from consiz.platform.win32.popup import _dispatch, _get_root

WIDTH, HEIGHT = 480, 460
PAD = 20

USER_TYPES = ["Student", "CA / Accountant / Finance", "Business owner", "Working professional", "Other"]
REASONS = ["Summarizing text & documents", "Answering questions quickly",
           "Organizing / sorting files", "Translating between languages", "Just exploring"]

BG = "#16181d"
CARD = "#20232a"
FG = "#f0f2f5"
SUB = "#9aa0a6"
BORDER = "#323640"
ACCENT = "#4f8cff"
GOOD = "#10b981"
WARN = "#f5a623"


def _heading(parent, text, size=20):
    return tk.Label(parent, text=text, font=("Segoe UI Variable Display", size, "bold"),
                    fg=FG, bg=BG, anchor="w", justify="left")


def _body(parent, text, size=11):
    return tk.Label(parent, text=text, font=("Segoe UI", size), fg=FG, bg=BG,
                    anchor="w", justify="left", wraplength=WIDTH - 2 * PAD)


def _sub(parent, text, size=9):
    return tk.Label(parent, text=text, font=("Segoe UI", size), fg=SUB, bg=BG,
                    anchor="w", justify="left", wraplength=WIDTH - 2 * PAD)


class OnboardingUI:
    def __init__(self):
        self.window: tk.Toplevel | None = None
        self.page = 0
        self.pages: list[tk.Frame] = []
        self.step_lbl: tk.Label | None = None
        self.back_btn: tk.Button | None = None
        self.next_btn: tk.Button | None = None
        # page 1 (about you) — StringVars need a live Tk root, so these are created in _build(), not here
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
        self.provider_var = tk.StringVar(value=CONFIG.provider if CONFIG.provider in ("openrouter", "ollama") else "openrouter")

        win = tk.Toplevel(root)
        win.title("Welcome to Consiz")
        win.configure(bg=BG)
        win.geometry(f"{WIDTH}x{HEIGHT}")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        self.window = win

        self.step_lbl = tk.Label(win, text="", font=("Segoe UI", 9), fg=SUB, bg=BG)
        self.step_lbl.place(x=PAD, y=12)

        body_area = tk.Frame(win, bg=BG)
        body_area.place(x=PAD, y=40, width=WIDTH - 2 * PAD, height=HEIGHT - 100)

        self.pages = [tk.Frame(body_area, bg=BG) for _ in range(4)]
        self._build_page0(self.pages[0])
        self._build_page1(self.pages[1])
        self._build_page2(self.pages[2])
        self._build_page3(self.pages[3])

        footer = tk.Frame(win, bg=BG)
        footer.place(x=PAD, y=HEIGHT - 50, width=WIDTH - 2 * PAD, height=36)

        self.back_btn = tk.Button(footer, text="Back", font=("Segoe UI", 9), command=lambda: self.go(self.page - 1),
                                  bg=CARD, fg=FG, activebackground=CARD, activeforeground=FG,
                                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2")
        self.back_btn.pack(side="left")

        self.next_btn = tk.Button(footer, text="Continue", font=("Segoe UI", 9, "bold"), command=self._on_next,
                                  bg=ACCENT, fg="#ffffff", activebackground=ACCENT, activeforeground="#ffffff",
                                  relief="flat", bd=0, padx=18, pady=6, cursor="hand2")
        self.next_btn.pack(side="right")

    def _build_page0(self, f: tk.Frame) -> None:
        _heading(f, "Welcome to Consiz").pack(anchor="w", pady=(0, 16))
        _body(f,
            "Consiz is a small assistant that lives quietly in the background of your Windows PC.\n\n"
            "Select anything on your screen — a sentence, a question, a whole file, or a folder — "
            f"then press the middle mouse button (or {CONFIG.hotkey}).\n\n"
            "Consiz reads exactly what you selected and answers, explains, or summarizes it right there "
            "next to your cursor. No app to open, no typing a question first.\n\n"
            "This takes about a minute to set up."
        ).pack(anchor="w", fill="x")

    def _build_page1(self, f: tk.Frame) -> None:
        _heading(f, "A little about you", size=17).pack(anchor="w", pady=(0, 4))
        _sub(f, "Consiz uses this to write answers and drafts that sound like they're for you — "
                "never shown to anyone else, and skipped entirely for plain questions."
             ).pack(anchor="w", fill="x", pady=(0, 18))

        tk.Label(f, text="Your name (optional)", font=("Segoe UI", 10), fg=FG, bg=BG, anchor="w").pack(anchor="w")
        tk.Entry(f, textvariable=self.name_var, font=("Segoe UI", 10), fg=FG, bg=CARD,
                 insertbackground=FG, relief="flat", highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT).pack(anchor="w", fill="x", ipady=5, pady=(4, 16))

        tk.Label(f, text="What best describes you?", font=("Segoe UI", 10), fg=FG, bg=BG, anchor="w").pack(anchor="w")
        self.type_var = tk.StringVar(value=USER_TYPES[0])
        tk.OptionMenu(f, self.type_var, *USER_TYPES).pack(anchor="w", fill="x", pady=(4, 16))

        tk.Label(f, text="Why are you using Consiz?", font=("Segoe UI", 10), fg=FG, bg=BG, anchor="w").pack(anchor="w")
        self.reason_var = tk.StringVar(value=REASONS[0])
        tk.OptionMenu(f, self.reason_var, *REASONS).pack(anchor="w", fill="x", pady=(4, 0))

    def _build_page2(self, f: tk.Frame) -> None:
        _heading(f, "Choose your AI", size=17).pack(anchor="w", pady=(0, 14))

        radios = tk.Frame(f, bg=BG)
        radios.pack(anchor="w", fill="x")
        tk.Radiobutton(radios, text="Cloud (OpenRouter) — free, needs internet", variable=self.provider_var,
                       value="openrouter", command=self._refresh_ai_state, font=("Segoe UI", 10),
                       fg=FG, bg=BG, selectcolor=CARD, activebackground=BG, activeforeground=FG,
                       anchor="w").pack(anchor="w", fill="x")
        tk.Radiobutton(radios, text=f"Offline ({CONFIG.ollama_model}) — private, no internet needed",
                       variable=self.provider_var, value="ollama", command=self._refresh_ai_state,
                       font=("Segoe UI", 10), fg=FG, bg=BG, selectcolor=CARD, activebackground=BG,
                       activeforeground=FG, anchor="w").pack(anchor="w", fill="x")

        self.cloud_frame = tk.Frame(f, bg=BG)
        row = tk.Frame(self.cloud_frame, bg=BG)
        row.pack(fill="x", pady=(10, 2))
        self._key_entry = tk.Entry(row, font=("Segoe UI", 9), fg=FG, bg=CARD,
                                   insertbackground=FG, relief="flat", highlightthickness=1,
                                   highlightbackground=BORDER, highlightcolor=ACCENT)
        self._key_entry.pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row, text="Save Key", font=("Segoe UI", 9), command=self._save_key,
                 bg=CARD, fg=FG, activebackground=CARD, activeforeground=FG,
                 relief="flat", bd=1, highlightbackground=BORDER, padx=10, cursor="hand2").pack(side="left", padx=(8, 0))
        _sub(self.cloud_frame, "Get a free key at: openrouter.ai/keys").pack(anchor="w")

        self.offline_frame = tk.Frame(f, bg=BG)
        _sub(self.offline_frame,
             "Needs Ollama installed separately (ollama.com/download), then run:\n"
             f"    ollama pull {CONFIG.ollama_model}"
             ).pack(anchor="w", pady=(10, 2))

        self.ai_status = tk.Label(f, text="", font=("Segoe UI", 10), fg=SUB, bg=BG, anchor="w",
                                  justify="left", wraplength=WIDTH - 2 * PAD)
        self.ai_status.pack(anchor="w", fill="x", pady=(14, 0))

        _sub(f, "You can change this anytime later by editing the .env file.").pack(anchor="w", pady=(24, 0))

    def _build_page3(self, f: tk.Frame) -> None:
        _heading(f, "You're all set!", size=20).pack(anchor="w", pady=(0, 16))
        _body(f,
            "From now on, on any file or selected text:\n\n"
            f"•  Select it, then press the middle mouse button (or {CONFIG.hotkey}) — Consiz answers, "
            "explains, or summarizes it.\n\n"
            "•  After an answer appears, type a follow-up question right there and press Enter.\n\n"
            "•  Click Copy on any answer to put it on your clipboard.\n\n"
            "That's it. Thank you for trying Consiz."
        ).pack(anchor="w", fill="x")

    # ---------------------------------------------------------------- navigation
    def go(self, page: int) -> None:
        page = max(0, min(page, len(self.pages) - 1))
        for p in self.pages:
            p.pack_forget()
        self.pages[page].pack(fill="both", expand=True)
        self.page = page
        self.step_lbl.configure(text=f"Step {page + 1} of {len(self.pages)}")
        self.back_btn.configure(state="disabled" if page == 0 else "normal")
        self.next_btn.configure(text="Get Started" if page == 0 else
                                ("Finish Setup" if page == len(self.pages) - 1 else "Continue"))
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
                text="✓ Key saved — Cloud is ready." if has_key else
                     "Paste your free OpenRouter key above, then click Save Key.",
                fg=GOOD if has_key else SUB)
        else:
            self.cloud_frame.pack_forget()
            self.offline_frame.pack(fill="x")
            self.ai_status.configure(text="Checking for Ollama…", fg=SUB)
            threading.Thread(target=self._check_ollama, daemon=True).start()

    def _check_ollama(self) -> None:
        from consiz.llm import _health_ollama
        ok, msg = _health_ollama()
        _dispatch(self._on_ollama_status, ok, msg)

    def _on_ollama_status(self, ok: bool, msg: str) -> None:
        if self.provider_var.get() != "ollama":
            return   # user switched away while the check was running
        self.ai_status.configure(text=("✓ " if ok else "⚠ ") + msg, fg=GOOD if ok else WARN)

    def _save_key(self) -> None:
        key = self._key_entry.get().strip()
        if not key:
            self.ai_status.configure(text="⚠ Paste your OpenRouter API key first.", fg=WARN)
            return
        if not key.startswith("sk-or-"):
            self.ai_status.configure(text="⚠ That doesn't look like an OpenRouter key (should start with sk-or-).", fg=WARN)
            return
        set_openrouter_key(key)
        CONFIG.provider = "openrouter"
        self.provider_var.set("openrouter")
        self._key_entry.delete(0, "end")
        self.ai_status.configure(text="✓ Key saved — Cloud is ready!", fg=GOOD)

    # ---------------------------------------------------------------- finish
    def finish(self) -> None:
        from consiz import prefs
        name = self.name_var.get()
        utype = self.type_var.get() if self.type_var is not None else ""
        reason = self.reason_var.get() if self.reason_var is not None else ""
        try:
            save_profile_basics(name, utype, reason)
        except OSError:
            pass   # profile personalization is a nice-to-have — never blocks finishing onboarding
        CONFIG.provider = self.provider_var.get()
        prefs.set("provider", CONFIG.provider)
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
