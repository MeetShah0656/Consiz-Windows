"""Settings and API Key configuration dialog for Consiz (Win32) — Cream & Maroon Redesign.

Restyled according to consiz-cream-maroon-ui-redesign.md.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional
import webbrowser

from consiz import prefs
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


def get_stored_api_key() -> str:
    """Retrieve existing key from prefs or environment."""
    return os.environ.get("OPENROUTER_API_KEY", "") or prefs.get("openrouter_api_key", "") or ""


def save_api_key(key: str) -> None:
    """Persist API key to ~/.consiz/prefs.json and current environment."""
    k = key.strip()
    prefs.set("openrouter_api_key", k)
    os.environ["OPENROUTER_API_KEY"] = k


def show_settings_dialog(parent: Optional[tk.Tk] = None, on_saved: Optional[Callable[[str], None]] = None) -> None:
    """Open the Consiz API Key configuration dialog. Runs on Tkinter main thread."""
    created_root = False
    if parent is None:
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()
            created_root = True
    else:
        root = parent

    win = tk.Toplevel(root)
    win.title("Consiz Settings — Preferences")
    win.configure(bg=CREAM_100)
    win.resizable(False, False)
    win.attributes("-topmost", True)

    # Window dimensions & centering
    width, height = 520, 440
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")

    # Main container
    container = tk.Frame(win, bg=CREAM_100, padx=26, pady=22)
    container.pack(fill="both", expand=True)

    # Header
    hdr_frame = tk.Frame(container, bg=CREAM_100)
    hdr_frame.pack(fill="x", pady=(0, 16))

    icon_lbl = tk.Label(hdr_frame, text="✦", font=(FONT_DISPLAY, 20), bg=CREAM_100, fg=MAROON_700)
    icon_lbl.pack(side="left", padx=(0, 10))

    title_box = tk.Frame(hdr_frame, bg=CREAM_100)
    title_box.pack(side="left", fill="x", expand=True)

    title_lbl = tk.Label(
        title_box,
        text="Consiz Preferences",
        font=(FONT_DISPLAY, 13, "bold"),
        bg=CREAM_100,
        fg=MAROON_900,
        anchor="w",
    )
    title_lbl.pack(fill="x")

    subtitle_lbl = tk.Label(
        title_box,
        text="Manage your AI backend connection, credentials, and answer language.",
        font=(FONT_TEXT, 9),
        bg=CREAM_100,
        fg=INK_MUTED,
        anchor="w",
    )
    subtitle_lbl.pack(fill="x")

    # Key Input Card
    card = tk.Frame(container, bg=CREAM_50, bd=1, relief="solid", highlightbackground=CREAM_300, padx=16, pady=16)
    card.pack(fill="x", pady=(0, 14))

    key_lbl = tk.Label(
        card,
        text="OpenRouter API Key:",
        font=(FONT_TEXT, 9, "bold"),
        bg=CREAM_50,
        fg=MAROON_800,
    )
    key_lbl.pack(anchor="w", pady=(0, 6))

    input_frame = tk.Frame(card, bg=CREAM_50)
    input_frame.pack(fill="x")

    key_var = tk.StringVar(value=get_stored_api_key())
    show_key = tk.BooleanVar(value=False)

    entry = tk.Entry(
        input_frame,
        textvariable=key_var,
        font=("Consolas", 10),
        bg=CREAM_50,
        fg=MAROON_900,
        insertbackground=MAROON_900,
        relief="flat",
        highlightbackground=CREAM_300,
        highlightcolor=FOCUS_RING,
        highlightthickness=1,
        show="•",
    )
    entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))

    def toggle_show():
        if show_key.get():
            entry.config(show="")
            eye_btn.config(text="Hide")
        else:
            entry.config(show="•")
            eye_btn.config(text="Show")

    def on_eye_click():
        show_key.set(not show_key.get())
        toggle_show()

    eye_btn = tk.Button(
        input_frame,
        text="Show",
        command=on_eye_click,
        font=(FONT_TEXT, 8, "bold"),
        bg=CREAM_200,
        fg=MAROON_800,
        activebackground=CREAM_300,
        activeforeground=MAROON_900,
        relief="flat",
        bd=1,
        highlightbackground=CREAM_300,
        padx=10,
        pady=3,
        cursor="hand2",
    )
    eye_btn.pack(side="right")

    # Language Selection Row
    lang_sep = tk.Frame(card, bg=CREAM_300, height=1)
    lang_sep.pack(fill="x", pady=(14, 12))

    lang_lbl = tk.Label(
        card,
        text="Default Answer Language:",
        font=(FONT_TEXT, 9, "bold"),
        bg=CREAM_50,
        fg=MAROON_800,
    )
    lang_lbl.pack(anchor="w", pady=(0, 6))

    from consiz.languages import LANGUAGES, CODES
    from consiz.config import CONFIG

    lang_display_names = [
        f"{lbl} ({name})" if code != "auto" else "Auto (Matches selected text)"
        for code, lbl, name, _ in LANGUAGES
    ]
    curr_code = CONFIG.answer_language
    curr_idx = CODES.index(curr_code) if curr_code in CODES else 0

    lang_combo_var = tk.StringVar(value=lang_display_names[curr_idx])

    # Configure ttk style for Combobox
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Cream.TCombobox",
        fieldbackground=CREAM_50,
        background=CREAM_200,
        foreground=MAROON_900,
        darkcolor=CREAM_300,
        lightcolor=CREAM_300,
        bordercolor=CREAM_300,
    )

    lang_combo = ttk.Combobox(
        card,
        textvariable=lang_combo_var,
        values=lang_display_names,
        state="readonly",
        font=(FONT_TEXT, 9),
        style="Cream.TCombobox",
    )
    lang_combo.current(curr_idx)
    lang_combo.pack(fill="x")

    # Link / Hint
    hint_frame = tk.Frame(container, bg=CREAM_100)
    hint_frame.pack(fill="x", pady=(0, 16))

    hint_lbl = tk.Label(
        hint_frame,
        text="💡 Don't have a key? OpenRouter offers 50+ free model requests daily.",
        font=(FONT_TEXT, 8),
        bg=CREAM_100,
        fg=INK_MUTED,
        anchor="w",
    )
    hint_lbl.pack(fill="x")

    link_lbl = tk.Label(
        hint_frame,
        text="👉 Click here to get a free API Key at openrouter.ai/keys",
        font=(FONT_TEXT, 8, "underline"),
        bg=CREAM_100,
        fg=MAROON_700,
        cursor="hand2",
        anchor="w",
    )
    link_lbl.pack(fill="x", pady=(2, 0))
    link_lbl.bind("<Button-1>", lambda e: webbrowser.open("https://openrouter.ai/keys"))
    link_lbl.bind("<Enter>", lambda e: link_lbl.configure(fg=MAROON_600))
    link_lbl.bind("<Leave>", lambda e: link_lbl.configure(fg=MAROON_700))

    # Status Message Label
    status_lbl = tk.Label(container, text="", font=(FONT_TEXT, 9, "bold"), bg=CREAM_100, fg=SUCCESS)
    status_lbl.pack(fill="x", pady=(0, 8))

    # Buttons Frame
    btn_frame = tk.Frame(container, bg=CREAM_100)
    btn_frame.pack(fill="x", side="bottom")

    def do_save():
        key = key_var.get().strip()
        if not key:
            status_lbl.config(text="⚠️ Please enter an API key.", fg=WARNING)
            return

        save_api_key(key)

        # Save selected answer language
        sel_idx = lang_combo.current()
        if 0 <= sel_idx < len(CODES):
            chosen_code = CODES[sel_idx]
            CONFIG.answer_language = chosen_code
            prefs.set("answer_language", chosen_code)

        status_lbl.config(text="✓ Preferences saved and activated!", fg=SUCCESS)
        if on_saved:
            try:
                on_saved(key)
            except Exception:
                pass
        win.after(700, win.destroy)

    def do_cancel():
        win.destroy()

    save_btn = tk.Button(
        btn_frame,
        text="Save & Activate",
        command=do_save,
        font=(FONT_TEXT, 9, "bold"),
        bg=MAROON_700,
        fg=CREAM_50,
        activebackground=MAROON_600,
        activeforeground=CREAM_50,
        relief="flat",
        bd=0,
        padx=18,
        pady=6,
        cursor="hand2",
    )
    save_btn.pack(side="right", padx=(8, 0))
    save_btn.bind("<Enter>", lambda e: save_btn.configure(bg=MAROON_600))
    save_btn.bind("<Leave>", lambda e: save_btn.configure(bg=MAROON_700))

    cancel_btn = tk.Button(
        btn_frame,
        text="Close",
        command=do_cancel,
        font=(FONT_TEXT, 9, "bold"),
        bg=CREAM_50,
        fg=MAROON_800,
        activebackground=CREAM_200,
        activeforeground=MAROON_900,
        relief="flat",
        bd=1,
        highlightbackground=CREAM_300,
        highlightthickness=1,
        padx=14,
        pady=6,
        cursor="hand2",
    )
    cancel_btn.pack(side="right")
    cancel_btn.bind("<Enter>", lambda e: cancel_btn.configure(bg=CREAM_200))
    cancel_btn.bind("<Leave>", lambda e: cancel_btn.configure(bg=CREAM_50))

    win.bind("<Return>", lambda e: do_save())
    win.bind("<Escape>", lambda e: do_cancel())

    win.focus_set()
    entry.focus_set()

    if created_root:
        root.mainloop()
