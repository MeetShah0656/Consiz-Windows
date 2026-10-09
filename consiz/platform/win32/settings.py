"""Settings window for Consiz (Win32), Cream & Maroon theme (T-09).

Five tabs: General · Mouse · Shortcuts · PC mode · Account & data. Every control applies at once (no Save button to forget);
the AI key box appears only in developer builds that talk to OpenRouter directly: end users sign in with Google.
Logic that is not drawing lives in consiz/hotkeys.py, consiz/localdata.py, consiz/pause.py and consiz/prefs.py.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional
import webbrowser

from consiz import history, hotkeys, i18n, pause, prefs, voice
from consiz.config import CONFIG
from consiz.platform.win32 import a11y, dpi
from consiz.platform.win32.dpi import px
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

_OPEN: dict = {"win": None}


def get_stored_api_key() -> str:
    """Retrieve existing key from prefs or environment (developer builds only)."""
    return os.environ.get("OPENROUTER_API_KEY", "") or prefs.get("openrouter_api_key", "") or ""


def save_api_key(key: str) -> None:
    """Persist API key to ~/.consiz/prefs.json and current environment."""
    k = key.strip()
    prefs.set("openrouter_api_key", k)
    os.environ["OPENROUTER_API_KEY"] = k


# ------------------------------------------------------------------ small widgets
def _section(parent, text: str) -> tk.Label:
    lbl = tk.Label(parent, text=text, font=(FONT_TEXT, 10, "bold"), bg=CREAM_50, fg=MAROON_800, anchor="w")
    lbl.pack(fill="x", pady=(px(14), px(4)))
    return lbl


_NOTES: list = []          # explanatory labels: their line length follows the width of the window (see new_tab)


def _note(parent, text: str, wrap: int = 500) -> tk.Label:
    lbl = tk.Label(parent, text=text, font=(FONT_TEXT, 8), bg=CREAM_50, fg=INK_MUTED, anchor="w", justify="left",
                   wraplength=px(wrap))
    lbl.pack(fill="x", pady=(0, px(4)))
    _NOTES.append(lbl)
    return lbl


def _check(parent, text: str, var: tk.BooleanVar, command: Callable[[], None]) -> tk.Checkbutton:
    cb = tk.Checkbutton(parent, text=text, variable=var, command=command, font=(FONT_TEXT, 10), bg=CREAM_50,
                        fg=MAROON_900, selectcolor=CREAM_50, activebackground=CREAM_50, activeforeground=MAROON_900,
                        anchor="w", justify="left")
    cb.pack(fill="x", pady=(px(2), 0))
    return cb


def _radio(parent, text: str, var: tk.StringVar, value: str, command: Callable[[], None]) -> tk.Radiobutton:
    rb = tk.Radiobutton(parent, text=text, variable=var, value=value, command=command, font=(FONT_TEXT, 10),
                        bg=CREAM_50, fg=MAROON_900, selectcolor=CREAM_50, activebackground=CREAM_50,
                        activeforeground=MAROON_900, anchor="w", justify="left")
    rb.pack(fill="x", pady=(px(2), 0))
    return rb


def _button(parent, text: str, command: Callable[[], None], primary: bool = False) -> tk.Button:
    b = tk.Button(parent, text=text, command=command, font=(FONT_TEXT, 9, "bold"),
                  bg=MAROON_700 if primary else CREAM_200, fg=CREAM_50 if primary else MAROON_800,
                  activebackground=MAROON_600 if primary else CREAM_300, activeforeground=CREAM_50 if primary else MAROON_900,
                  relief="flat", bd=0, padx=px(12), pady=px(5), cursor="hand2")
    return b


def _entry(parent, var: tk.StringVar, width: int = 0) -> tk.Entry:
    e = tk.Entry(parent, textvariable=var, font=(FONT_TEXT, 10), bg=CREAM_50, fg=MAROON_900, insertbackground=MAROON_900,
                 relief="flat", highlightthickness=1, highlightbackground=CREAM_300, highlightcolor=FOCUS_RING)
    if width:
        e.config(width=width)
    return e


def show_settings_dialog(parent: Optional[tk.Tk] = None, on_saved: Optional[Callable[[str], None]] = None,
                         on_sign_out: Optional[Callable[[], None]] = None,
                         on_reset_popup: Optional[Callable[[], None]] = None) -> None:
    """Open the Consiz Settings window. Runs on the Tkinter main thread."""
    if _OPEN["win"] is not None:
        try:
            _OPEN["win"].deiconify()
            _OPEN["win"].lift()
            return
        except tk.TclError:
            _OPEN["win"] = None

    created_root = False
    if parent is None:
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()
            created_root = True
    else:
        root = parent

    from consiz import auth, llm, localdata, pc_mode
    from consiz.languages import CODES, LANGUAGES
    from consiz.platform.win32 import mousegate, tray

    win = tk.Toplevel(root)
    _OPEN["win"] = win
    win.title("Consiz Settings")
    win.configure(bg=CREAM_100)
    win.attributes("-topmost", True)
    _NOTES.clear()
    # Open on the screen the mouse is on, never bigger than it (a 1366x768 laptop at 125 % has only ~580 px of height);
    # the tabs scroll when there is not enough room, and the window can be resized.
    area = dpi.work_area_at(win.winfo_pointerx(), win.winfo_pointery())
    width, height = dpi.fit_size((px(620), px(830)), area, fraction=0.9)    # 0.9: leaves room for the title bar
    win.geometry(f"{width}x{height}+{area[0] + max(0, (area[2] - area[0] - width) // 2)}+"
                 f"{area[1] + max(0, (area[3] - area[1] - height) // 3)}")
    win.minsize(min(px(460), width), min(px(340), height))
    win.resizable(True, True)

    def _closed(*_):
        _OPEN["win"] = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", _closed)
    win.bind("<Escape>", _closed)

    # ---- header
    hdr = tk.Frame(win, bg=CREAM_100)
    hdr.pack(fill="x", padx=px(24), pady=(px(18), px(8)))
    tk.Label(hdr, text="✦", font=(FONT_DISPLAY, 20), bg=CREAM_100, fg=MAROON_700).pack(side="left", padx=(0, px(10)))
    box = tk.Frame(hdr, bg=CREAM_100)
    box.pack(side="left", fill="x", expand=True)
    tk.Label(box, text="Settings", font=(FONT_DISPLAY, 14, "bold"), bg=CREAM_100, fg=MAROON_900, anchor="w").pack(fill="x")
    tk.Label(box, text="Changes apply at once.", font=(FONT_TEXT, 9), bg=CREAM_100, fg=INK_MUTED, anchor="w").pack(fill="x")

    # ---- footer (status + Close) first, so the tabs get the leftover space
    foot = tk.Frame(win, bg=CREAM_100)
    foot.pack(side="bottom", fill="x", padx=px(24), pady=(px(6), px(16)))
    status = tk.Label(foot, text="", font=(FONT_TEXT, 9, "bold"), bg=CREAM_100, fg=SUCCESS, anchor="w")
    status.pack(side="left", fill="x", expand=True)
    _button(foot, "Close", _closed).pack(side="right")

    def say(text: str, ok: bool = True) -> None:
        shown = i18n.t(text)
        status.config(text=shown, fg=SUCCESS if ok else WARNING)
        win.after(3500, lambda: status.config(text="") if status.cget("text") == shown else None)

    # ---- tabs
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Cream.TNotebook", background=CREAM_100, borderwidth=0)
    style.configure("Cream.TNotebook.Tab", background=CREAM_200, foreground=MAROON_800, padding=(px(14), px(6)),
                    font=(FONT_TEXT, 9, "bold"), borderwidth=0)
    style.map("Cream.TNotebook.Tab", background=[("selected", CREAM_50)], foreground=[("selected", MAROON_900)])
    style.configure("Cream.TCombobox", fieldbackground=CREAM_50, background=CREAM_200, foreground=MAROON_900,
                    darkcolor=CREAM_300, lightcolor=CREAM_300, bordercolor=CREAM_300)
    book = ttk.Notebook(win, style="Cream.TNotebook")
    book.pack(fill="both", expand=True, padx=px(24), pady=(0, px(4)))

    def new_tab(title: str) -> tk.Frame:
        """A tab whose content scrolls (scroll bar only when needed) and re-wraps its notes to the window width."""
        outer = tk.Frame(book, bg=CREAM_50, highlightbackground=CREAM_300, highlightthickness=1)
        canvas = tk.Canvas(outer, bg=CREAM_50, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        holder = tk.Frame(canvas, bg=CREAM_50)
        holder_id = canvas.create_window((0, 0), window=holder, anchor="nw")
        content = tk.Frame(holder, bg=CREAM_50)
        content.pack(fill="both", expand=True, padx=px(18), pady=(0, px(12)))

        def sync(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            if holder.winfo_reqheight() > canvas.winfo_height() > 1:
                if not bar.winfo_ismapped():
                    bar.pack(side="right", fill="y", before=canvas)
            elif bar.winfo_ismapped():
                bar.pack_forget()
                canvas.yview_moveto(0)

        def on_canvas(e):
            canvas.itemconfigure(holder_id, width=e.width)
            wrap = max(px(200), e.width - 2 * px(18) - px(8))
            for note in _NOTES:
                if str(note).startswith(str(content)):
                    note.configure(wraplength=wrap)
            sync()

        def wheel(e):
            if bar.winfo_ismapped():
                canvas.yview_scroll(int(-e.delta / 120), "units")

        holder.bind("<Configure>", sync)
        canvas.bind("<Configure>", on_canvas)
        outer.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        outer.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        canvas.pack(side="left", fill="both", expand=True)
        book.add(outer, text=i18n.t(title))
        return content

    # =============================================================== General
    g = new_tab("General")
    _section(g, "Answer language")
    names = [f"{lbl} ({name})" if code != "auto" else i18n.t("Auto (matches the selected text)") for code, lbl, name, _ in LANGUAGES]
    lang_var = tk.StringVar(value=names[CODES.index(CONFIG.answer_language) if CONFIG.answer_language in CODES else 0])
    combo = ttk.Combobox(g, textvariable=lang_var, values=names, state="readonly", font=(FONT_TEXT, 10), style="Cream.TCombobox")
    combo.pack(fill="x")
    win._keep = [lang_var]                    # a Tk variable that nothing refers to is deleted, and its combobox goes blank

    def on_lang(_e=None):
        i = combo.current()
        if 0 <= i < len(CODES):
            CONFIG.answer_language = CODES[i]
            prefs.set("answer_language", CODES[i])
            say("Answer language saved ✓")

    combo.bind("<<ComboboxSelected>>", on_lang)

    _section(g, "App language")
    ui_codes = list(i18n.LANGUAGES)
    ui_names = [i18n.LANGUAGES[c] for c in ui_codes]
    ui_var = tk.StringVar(value=i18n.LANGUAGES.get(prefs.get("ui_language", "auto"), ui_names[0]))
    ui_combo = ttk.Combobox(g, textvariable=ui_var, values=ui_names, state="readonly", font=(FONT_TEXT, 10), style="Cream.TCombobox")
    ui_combo.pack(fill="x")
    win._keep.append(ui_var)
    _note(g, "The words in Consiz's own windows. Restart Consiz to apply. (The language of the answers is set above, under "
             "Answer language.)")

    def on_ui_lang(_e=None):
        i = ui_combo.current()
        if 0 <= i < len(ui_codes):
            prefs.set("ui_language", ui_codes[i])
            say("Restart Consiz for the new language to apply.")

    ui_combo.bind("<<ComboboxSelected>>", on_ui_lang)

    _section(g, "Start with Windows")
    auto_var = tk.BooleanVar(value=tray.is_autostart_enabled())
    _check(g, "Start Consiz when I sign in to Windows", auto_var,
           lambda: (tray.set_autostart_enabled(auto_var.get()), say("Saved ✓")))

    _section(g, "Where answers come from")
    server = llm.server_mode()
    src_var = tk.StringVar(value="ollama" if CONFIG.provider == "ollama" else "openrouter")

    def on_source():
        CONFIG.provider = src_var.get()
        prefs.set("provider", CONFIG.provider)
        say("AI source saved ✓")

    _radio(g, "Consiz cloud (needs internet; sign in with Google)" if server else "OpenRouter (uses the key below)",
           src_var, "openrouter", on_source)
    _radio(g, f"Offline on this PC ({CONFIG.ollama_model} through Ollama): private, slower", src_var, "ollama", on_source)
    fb_var = tk.BooleanVar(value=bool(prefs.get("offline_fallback", True)))
    _check(g, "If the cloud cannot be reached, answer offline when Ollama is running", fb_var,
           lambda: (prefs.set("offline_fallback", fb_var.get()), say("Saved ✓")))

    _section(g, "Voice dictation")
    if not voice.available():
        _note(g, "Voice dictation is not included in this version of Consiz.")
    else:
        voice_var = tk.BooleanVar(value=bool(prefs.get("voice_enabled", True)))
        _check(g, "Let me speak to Consiz (microphone button and the Voice shortcut)", voice_var,
               lambda: (prefs.set("voice_enabled", voice_var.get()), say("Saved ✓")))
        _note(g, "Your voice is turned into text on this PC and the audio is never uploaded: only the words you "
                 "say are sent to the AI, like a typed question.")
        names_by_label = {f"{label} (~{mb} MB)": name for name, (label, mb) in voice.MODELS.items()}
        current_label = next((lbl for lbl, nm in names_by_label.items() if nm == CONFIG.whisper_model),
                             next(iter(names_by_label)))
        model_var = tk.StringVar(value=current_label)
        model_combo = ttk.Combobox(g, textvariable=model_var, values=list(names_by_label), state="readonly",
                                   font=(FONT_TEXT, 10), style="Cream.TCombobox")
        model_combo.pack(fill="x", pady=(px(4), 0))
        model_status = _note(g, "")

        def show_model_status():
            name = names_by_label[model_var.get()]
            model_status.config(text="Speech model: downloaded, works offline ✓" if voice.model_cached(name) else
                                f"Speech model: not downloaded yet. Consiz asks once, then downloads about "
                                f"{voice.model_mb(name)} MB the first time you speak.")

        def on_model(_e=None):
            from consiz import dictation
            name = names_by_label[model_var.get()]
            CONFIG.whisper_model = name
            prefs.set("whisper_model", name)
            dictation.reset_engine()
            show_model_status()
            say("Voice model saved ✓")

        model_combo.bind("<<ComboboxSelected>>", on_model)
        show_model_status()

    if not server:                                          # developer builds only
        _section(g, "OpenRouter API key (developer build)")
        key_var = tk.StringVar(value=get_stored_api_key())
        row = tk.Frame(g, bg=CREAM_50)
        row.pack(fill="x")
        ke = _entry(row, key_var)
        ke.config(show="•")
        ke.pack(side="left", fill="x", expand=True, ipady=px(4), padx=(0, px(8)))

        def save_key():
            k = key_var.get().strip()
            if not k:
                say("Paste a key first.", ok=False)
                return
            save_api_key(k)
            if on_saved:
                try:
                    on_saved(k)
                except Exception:
                    pass
            say("Key saved ✓")

        _button(row, "Save key", save_key, primary=True).pack(side="right")
        link = tk.Label(g, text="Get a free key at openrouter.ai/keys", font=(FONT_TEXT, 8, "underline"), bg=CREAM_50,
                        fg=MAROON_700, cursor="hand2", anchor="w")
        link.pack(fill="x", pady=(px(2), 0))
        link.bind("<Button-1>", lambda e: webbrowser.open("https://openrouter.ai/keys"))

    # =============================================================== Mouse & keys
    m = new_tab("Mouse")
    _section(m, "How to start Consiz with the mouse")
    mode_var = tk.StringVar(value=(os.environ.get("CONSIZ_TRIGGER_MODE") or prefs.get("trigger_mode") or mousegate.DEFAULT_MODE))
    if mode_var.get() not in mousegate.MODES:
        mode_var.set(mousegate.DEFAULT_MODE)
    labels = {"middle": "Middle click (given back to the app when nothing is selected)",
              "ctrl_middle": "Ctrl + middle click only (normal clicks are never touched)",
              "hotkey": "Keyboard only (the mouse is never touched)"}
    for mode in mousegate.MODES:
        _radio(m, labels[mode], mode_var, mode, lambda: (prefs.set("trigger_mode", mode_var.get()), say("Saved ✓")))

    _note(m, "Windows that run as administrator cannot be reached by the mouse or read by Consiz, unless Consiz is "
             "also started as administrator (right-click Consiz.exe, then Run as administrator).")

    _section(m, "Pause")
    paused_var = tk.BooleanVar(value=pause.is_paused())
    _check(m, "Pause Consiz now (mouse and shortcuts go back to your apps)", paused_var,
           lambda: pause.set_paused(paused_var.get()))
    fs_var = tk.BooleanVar(value=bool(prefs.get("pause_in_fullscreen", True)))
    _check(m, "Pause the mouse trigger while a full-screen app or a presentation is in front", fs_var,
           lambda: (prefs.set("pause_in_fullscreen", fs_var.get()), say("Saved ✓")))

    _section(m, "Programs where the middle button is left alone")
    _note(m, "Built in: " + ", ".join(sorted(mousegate.DEFAULT_EXCLUDED)[:6]) + " and other 3D / CAD tools. "
             "Add your own program names, separated by commas (for example: vlc.exe, mpc-hc64.exe).")
    ex_var = tk.StringVar(value=", ".join(prefs.get("trigger_excluded_apps") or []))
    ex_row = tk.Frame(m, bg=CREAM_50)
    ex_row.pack(fill="x")
    _entry(ex_row, ex_var).pack(side="left", fill="x", expand=True, ipady=px(4), padx=(0, px(8)))

    def save_excluded():
        names_ = []
        for part in ex_var.get().split(","):
            n = part.strip().lower()
            if n:
                names_.append(n if "." in n else n + ".exe")
        prefs.set("trigger_excluded_apps", names_)
        ex_var.set(", ".join(names_))
        say("Program list saved ✓")

    _button(ex_row, "Save", save_excluded, primary=True).pack(side="right")

    # =============================================================== Shortcuts
    k = new_tab("Shortcuts")
    _section(k, "Keyboard shortcuts")
    _note(k, "Use two modifiers (for example Ctrl+Alt+S) or one modifier with a function key (Ctrl+F9). "
             "A shortcut such as Ctrl+S alone would break Save in every app, so it is refused.")
    hk_rows = {}
    for label, pref_key, default in (("Explain selection", "hotkey_explain", "<ctrl>+<alt>+s"),
                                     ("Ask about my PC", "hotkey_pc", "<ctrl>+<alt>+a"),
                                     ("Voice dictation", "hotkey_dictate", "<ctrl>+<alt>+d")):
        row = tk.Frame(k, bg=CREAM_50)
        row.pack(fill="x", pady=(px(3), 0))
        tk.Label(row, text=label, font=(FONT_TEXT, 10), bg=CREAM_50, fg=MAROON_900, width=18, anchor="w").pack(side="left")
        current = {"hotkey_explain": CONFIG.hotkey, "hotkey_pc": CONFIG.pc_hotkey,
                   "hotkey_dictate": CONFIG.dictate_hotkey}[pref_key]
        var = tk.StringVar(value=hotkeys.pretty(current))
        _entry(row, var, width=16).pack(side="left", ipady=px(3))
        hk_rows[pref_key] = (var, default)

    def apply_hotkeys(reset: bool = False):
        values = {}
        for pref_key, (var, default) in hk_rows.items():
            text = default if reset else var.get()
            norm = hotkeys.normalize(text)
            if norm is None:
                say("That shortcut is not allowed. Try Ctrl+Alt+<letter>.", ok=False)
                return
            values[pref_key] = norm
        if len(set(values.values())) != len(values):
            say("The shortcuts must all be different.", ok=False)
            return
        for pref_key, norm in values.items():
            prefs.set(pref_key, norm)
            hk_rows[pref_key][0].set(hotkeys.pretty(norm))
        CONFIG.hotkey, CONFIG.pc_hotkey = values["hotkey_explain"], values["hotkey_pc"]
        CONFIG.dictate_hotkey = values["hotkey_dictate"]
        say("Shortcuts saved ✓ (active within a few seconds)")

    btns = tk.Frame(k, bg=CREAM_50)
    btns.pack(fill="x", pady=(px(6), 0))
    _button(btns, "Save shortcuts", apply_hotkeys, primary=True).pack(side="left")
    _button(btns, "Reset to default", lambda: apply_hotkeys(reset=True)).pack(side="left", padx=(px(8), 0))

    # =============================================================== PC mode

    _section(k, "Accessibility")
    focus_var = tk.BooleanVar(value=a11y.popup_takes_focus())
    _check(k, "Move the keyboard focus into the answer window when it opens", focus_var,
           lambda: (prefs.set("popup_takes_focus", focus_var.get()), say("Saved ✓")))
    _note(k, "Consiz follows the Windows settings for Text size and High contrast (restart Consiz after changing them). "
             "Every button in the answer window can be reached with the Tab key and pressed with Enter or Space. "
             "On while a screen reader is running.")

    p = new_tab("PC mode")
    _section(p, "Permission")
    perm_lbl = tk.Label(p, text="", font=(FONT_TEXT, 10), bg=CREAM_50, fg=MAROON_900, anchor="w")
    perm_lbl.pack(fill="x")

    _NOTES.append(perm_lbl)

    def refresh_perm():
        perm_lbl.config(text="Consiz may look at program names, memory use and window titles when you ask about your PC."
                        if prefs.get("pc_mode_consent") else "Not allowed yet. Consiz asks the first time you use Ask about my PC.",
                        justify="left")

    refresh_perm()
    prow = tk.Frame(p, bg=CREAM_50)
    prow.pack(fill="x", pady=(px(6), 0))
    _button(prow, "Forget my permission", lambda: (prefs.set("pc_mode_consent", False), refresh_perm(),
                                                   say("Consiz will ask again next time ✓"))).pack(side="left")
    _button(prow, "Forget windows I allowed", lambda: (pc_mode.forget_allowed_windows(),
                                                       say("Windows will ask permission again ✓"))).pack(side="left", padx=(px(8), 0))

    _section(p, "Windows Consiz never reads inside")
    _note(p, "Always blocked: password managers, remote desktop, and any window whose title looks like a password, bank, "
             "wallet or private-browsing page. Add your own words below, separated by commas (a window whose title or "
             "program name contains one is never read).")
    bl_var = tk.StringVar(value=", ".join(pc_mode.user_blocklist()))
    bl_row = tk.Frame(p, bg=CREAM_50)
    bl_row.pack(fill="x")
    _entry(bl_row, bl_var).pack(side="left", fill="x", expand=True, ipady=px(4), padx=(0, px(8)))

    def save_blocklist():
        words = [w.strip() for w in bl_var.get().split(",") if w.strip()]
        prefs.set("pc_blocklist_words", words)
        bl_var.set(", ".join(words))
        say("Never-read list saved ✓")

    _button(bl_row, "Save", save_blocklist, primary=True).pack(side="right")

    # =============================================================== Account & data

    _section(p, "PC watcher")
    watch_var = tk.BooleanVar(value=bool(prefs.get("watcher_enabled", False)))
    _check(p, "Tell me when my PC has been slow, full or short of disk space", watch_var,
           lambda: (prefs.set("watcher_enabled", watch_var.get()), say("Saved ✓")))
    _note(p, "Off until you turn it on. Every 30 seconds Consiz reads three numbers on this PC (CPU, memory, free disk). "
             "Nothing is sent anywhere, no AI is used, nothing is stored and nothing is closed. It only shows one small "
             "message when something stays high for a few minutes.")

    a = new_tab("Account & data")
    _section(a, "Account")
    if auth.enabled():
        who = tk.Label(a, text="", font=(FONT_TEXT, 10), bg=CREAM_50, fg=MAROON_900, anchor="w")
        who.pack(fill="x")
        out_btn = _button(a, "Sign out", lambda: None)

        def refresh_who():
            if auth.signed_in():
                who.config(text="Signed in as " + auth.display_name())
                out_btn.config(state="normal")
            else:
                who.config(text="Not signed in.")
                out_btn.config(state="disabled")

        def do_sign_out():
            if on_sign_out:
                on_sign_out()
            else:
                auth.sign_out()
            refresh_who()
            say("Signed out ✓")

        out_btn.config(command=do_sign_out)
        out_btn.pack(anchor="w", pady=(px(6), 0))
        refresh_who()
    else:
        _note(a, "Sign-in is not used in this build.")

    _section(a, "Answer window")
    _note(a, "Drag the corner of the answer window to resize it: Consiz remembers the size.")

    def reset_popup():
        prefs.set("popup_size", None)
        if on_reset_popup:
            on_reset_popup()
        say("Answer window size reset ✓")

    _button(a, "Reset answer window size", reset_popup).pack(anchor="w")

    _section(a, "Help")
    hrow = tk.Frame(a, bg=CREAM_50)
    hrow.pack(fill="x")

    def open_logs():
        from consiz import logs
        try:
            os.startfile(str(logs.log_folder()))
        except OSError:
            pass

    def copy_diag():
        from consiz import logs
        win.clipboard_clear()
        win.clipboard_append(logs.diagnostics())
        say("Diagnostics copied. Paste them into your message to support ✓")

    _button(hrow, "Open log folder", open_logs).pack(side="left")
    _button(hrow, "Copy diagnostics", copy_diag).pack(side="left", padx=(px(8), 0))

    _section(a, "Chat history")
    hist_var = tk.BooleanVar(value=history.enabled())
    _check(a, "Keep my chats on this PC so I can open them again", hist_var,
           lambda: (prefs.set("history_enabled", hist_var.get()), say("Saved ✓")))
    _note(a, "Off until you turn it on. Chats are saved only on this PC, never uploaded, with passwords and keys removed "
             "first. Tray > Recent chats opens one again. Each chat can also be saved as a text file from its window "
             "(Save as text), whether or not this is on.")
    hist_row = tk.Frame(a, bg=CREAM_50)
    hist_row.pack(fill="x", pady=(px(4), 0))
    _button(hist_row, "Open the folder", lambda: os.startfile(str(history.folder()))).pack(side="left")

    def delete_chats():
        n = history.count()
        if not n:
            say("There are no saved chats.")
            return
        if messagebox.askyesno("Consiz", i18n.tf("Delete all {n} saved chats from this PC? This cannot be undone.", n=n), parent=win):
            say(i18n.tf("Deleted {n} chats ✓", n=history.delete_all()))

    _button(hist_row, "Delete all saved chats", delete_chats).pack(side="left", padx=(px(8), 0))

    _section(a, "Your data on this PC")
    _note(a, "Clears your settings, the saved sign-in and the app log from this computer. Your profile.md is kept. "
             "Consiz shows the welcome screens again next time it starts.")

    def clear_all():
        if not messagebox.askyesno(i18n.t("Clear local data"), i18n.t(
                "Clear Consiz's settings, saved sign-in and log from this PC?\n\n"
                "You will be signed out. Consiz stays running until you restart it."), parent=win):
            return
        done = localdata.clear_local_data()
        if on_sign_out and auth.enabled():
            try:
                on_sign_out()
            except Exception:
                pass
        say(i18n.tf("Done ({n} item(s)). Restart Consiz to finish ✓", n=len(done)))

    _button(a, "Clear local data…", clear_all).pack(anchor="w", pady=(px(4), 0))

    from consiz import __version__, updater
    vrow = tk.Frame(a, bg=CREAM_50)
    vrow.pack(fill="x", side="bottom", pady=(px(8), 0))
    tk.Label(vrow, text=f"Consiz {__version__}", font=(FONT_TEXT, 8), bg=CREAM_50, fg=INK_MUTED, anchor="w").pack(side="left")

    def check_updates():
        import threading

        def work():
            info = updater.check()
            if info is None:
                msg, ok = "Could not check for updates. Try again later.", False
            elif info["required"] or info["update_available"]:
                msg, ok = f"Version {info['latest'] or 'newer'} is available: see the tray menu > Download.", True
            else:
                msg, ok = f"You have the latest version ({info['current']}) ✓", True
            try:
                win.after(0, lambda: say(msg, ok))
            except tk.TclError:
                pass
        threading.Thread(target=work, daemon=True).start()

    if llm.server_mode():
        link = tk.Label(vrow, text="Check for updates", font=(FONT_TEXT, 8, "underline"), bg=CREAM_50, fg=MAROON_700,
                        cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: check_updates())

    win.focus_set()
    if created_root:
        root.mainloop()
