"""Windows System Tray integration for Consiz.

Provides a lightweight background tray icon with status, quick action triggers,
boot autostart toggle, and clean process termination.
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Callable, Optional

try:
    from PIL import Image, ImageDraw
    import pystray
    from pystray import MenuItem as Item, Menu
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None

from consiz import pause

RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "Consiz"


def is_autostart_enabled() -> bool:
    """Check if Consiz is registered to start on Windows logon."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def set_autostart_enabled(enabled: bool) -> None:
    """Enable or disable start with Windows via HKCU Run registry."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                # Use current executable path (or python + script if not frozen)
                if getattr(sys, "frozen", False):
                    exe_path = f'"{sys.executable}"'
                else:
                    exe_path = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


def _create_default_icon_image() -> Image.Image:
    """Create a crisp in-memory icon matching the cream & maroon palette."""
    size = (64, 64)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded badge with rich maroon fill and warm cream border
    draw.rounded_rectangle([2, 2, 62, 62], radius=16, fill=(97, 30, 41, 255), outline=(221, 203, 176, 230), width=3)
    
    # Draw stylized 'C' in cream
    draw.arc([14, 14, 50, 50], start=45, end=315, fill=(255, 252, 246, 255), width=6)
    draw.ellipse([46, 14, 52, 20], fill=(239, 227, 208, 255))
    draw.ellipse([46, 44, 52, 50], fill=(239, 227, 208, 255))

    return img


def paused_icon_image(base: "Image.Image") -> "Image.Image":
    """The normal icon in grey with a pause sign, so a paused Consiz is obvious in the tray."""
    img = base.convert("RGBA").resize((64, 64)).convert("LA").convert("RGBA")
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([34, 34, 62, 62], radius=6, fill=(97, 30, 41, 255), outline=(255, 252, 246, 255), width=2)
    draw.rectangle([41, 40, 45, 56], fill=(255, 252, 246, 255))
    draw.rectangle([51, 40, 55, 56], fill=(255, 252, 246, 255))
    return img


def get_icon_image() -> Image.Image:
    """Retrieve icon from disk/bundle or generate fallback."""
    candidate_paths = []
    # If running in PyInstaller bundle
    if hasattr(sys, "_MEIPASS"):
        candidate_paths.append(os.path.join(sys._MEIPASS, "assets", "icon.ico"))
        candidate_paths.append(os.path.join(sys._MEIPASS, "icon.ico"))

    candidate_paths.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "icon.ico")))
    candidate_paths.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "icon.png")))

    for p in candidate_paths:
        if os.path.exists(p):
            try:
                return Image.open(p)
            except Exception:
                pass

    return _create_default_icon_image()


class SystemTray:
    def __init__(
        self,
        on_explain: Optional[Callable[[str], None]] = None,
        on_dictate: Optional[Callable[[str], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        on_sign_out: Optional[Callable[[], None]] = None,
        on_pc: Optional[Callable[[str], None]] = None,
        get_user_label: Optional[Callable[[], str]] = None,
        is_signed_in: Optional[Callable[[], bool]] = None,
        on_sign_in: Optional[Callable[[], None]] = None,
        welcome: str = "",
    ) -> None:
        self.welcome = welcome
        self.on_sign_out = on_sign_out
        self.on_pc = on_pc
        self.get_user_label = get_user_label
        self.is_signed_in = is_signed_in or (lambda: True)
        self.on_sign_in = on_sign_in
        self.on_explain = on_explain
        self.on_dictate = on_dictate
        self.on_settings = on_settings
        self.on_exit = on_exit
        self.icon: Optional[pystray.Icon] = None

    def _toggle_autostart(self, icon, item):
        new_state = not is_autostart_enabled()
        set_autostart_enabled(new_state)

    def _toggle_pause(self, icon, item):
        pause.toggle()

    def _on_pause_changed(self, paused: bool) -> None:
        """Grey icon + tooltip while paused; the menu text flips between Pause and Resume."""
        if not self.icon:
            return
        try:
            self.icon.icon = self._paused_image if paused else self._normal_image
            self.icon.title = "Consiz - paused" if paused else "Consiz — AI Context & Dictation"
            self.icon.update_menu()
            self.icon.notify("Consiz is paused. It will not touch your mouse or keyboard." if paused
                             else "Consiz is active again.", "Consiz")
        except Exception:
            pass

    def _trigger_explain(self, icon, item):
        if self.on_explain:
            threading.Thread(target=self.on_explain, args=("tray",), daemon=True).start()

    def _trigger_pc(self, icon, item):
        if self.on_pc:
            threading.Thread(target=self.on_pc, args=("tray",), daemon=True).start()

    def _trigger_dictate(self, icon, item):
        if self.on_dictate:
            threading.Thread(target=self.on_dictate, args=("tray",), daemon=True).start()

    def _open_settings(self, icon, item):
        if self.on_settings:
            self.on_settings()
        else:
            try:
                from .settings import show_settings_dialog
                show_settings_dialog()
            except Exception:
                pass

    def _sign_out(self, icon, item):
        if self.on_sign_out:
            self.on_sign_out()

    def _sign_in(self, icon, item):
        if self.on_sign_in:
            self.on_sign_in()

    def _open_logs(self, icon, item):
        from consiz import logs
        try:
            os.startfile(str(logs.log_folder()))
        except OSError:
            pass

    def _copy_diagnostics(self, icon, item):
        """Put version/settings/recent log lines on the clipboard so a user can paste them to support."""
        from consiz import logs
        try:
            import win32clipboard
            text = logs.diagnostics()
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            icon.notify("Diagnostics copied. Paste them into your message to support.", "Consiz")
        except Exception:
            logs.exception("copy diagnostics")

    def _quit_app(self, icon, item):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self.on_exit:
            self.on_exit()
        else:
            os._exit(0)

    def start(self) -> None:
        """Starts the tray icon in a non-blocking detached thread."""
        if pystray is None:
            return

        def autostart_checked(item):
            return is_autostart_enabled()

        def _make_lang_menu():
            from consiz.languages import LANGUAGES
            from consiz.config import CONFIG
            from consiz import prefs

            def select_lang(code):
                def _handler(icon, item):
                    CONFIG.answer_language = code
                    prefs.set("answer_language", code)
                return _handler

            def make_is_checked(code):
                def _check(item):
                    return CONFIG.answer_language == code
                return _check

            items = []
            for code, label, name, _ in LANGUAGES:
                display = f"{label} ({name})" if code != "auto" else "Auto (Match selection)"
                items.append(
                    Item(display, select_lang(code), checked=make_is_checked(code), radio=True)
                )
            return Menu(*items)

        def _make_trigger_menu():
            """How Consiz is started with the mouse. The trigger re-reads this setting within ~3 seconds."""
            from consiz import prefs
            from consiz.platform.win32.mousegate import DEFAULT_MODE, MODES

            labels = {"middle": "Middle click (passes through when nothing is selected)",
                      "ctrl_middle": "Ctrl + middle click only (never touches normal clicks)",
                      "hotkey": "Keyboard only (Ctrl+Alt+S / Ctrl+Alt+A)"}

            def current():
                import os
                m = os.environ.get("CONSIZ_TRIGGER_MODE") or prefs.get("trigger_mode") or DEFAULT_MODE
                return m if m in MODES else DEFAULT_MODE

            def choose(mode):
                def _handler(icon, item):
                    prefs.set("trigger_mode", mode)
                return _handler

            def is_on(mode):
                return lambda item: current() == mode

            return Menu(*[Item(labels[m], choose(m), checked=is_on(m), radio=True) for m in MODES])

        menu = Menu(
            Item(lambda item: "⏸ Consiz is paused" if pause.is_paused() else "⚡ Consiz is active", None, enabled=False),
            Item(lambda item: "▶ Resume Consiz" if pause.is_paused() else "⏸ Pause Consiz", self._toggle_pause),
            Item("Explain Selection (Ctrl+Alt+S)", self._trigger_explain),
            *([Item("Ask about my PC (Ctrl+Alt+A)", self._trigger_pc)] if self.on_pc else []),
            Item("Voice Dictate (Ctrl+Alt+D)", self._trigger_dictate),
            Menu.SEPARATOR,
            Item("🌐 Answer Language", _make_lang_menu()),
            Item("🖱 Trigger", _make_trigger_menu()),
            Item("⚙️ Configure API Key & Settings...", self._open_settings),
            Item("Start on Windows Boot", self._toggle_autostart, checked=autostart_checked),
            Item("Help && diagnostics", Menu(
                Item("Open log folder", self._open_logs),
                Item("Copy diagnostics for support", self._copy_diagnostics),
            )),
            Menu.SEPARATOR,
            *([Item(lambda item: self.get_user_label(), None, enabled=False)] if self.get_user_label else []),
            *([Item("Sign in…", self._sign_in, visible=lambda item: not self.is_signed_in())]
              if self.on_sign_in else []),
            *([Item("Sign out", self._sign_out, visible=lambda item: self.is_signed_in())]
              if self.on_sign_out else []),
            Item("Exit Consiz", self._quit_app),
        )



        image = get_icon_image()
        self._normal_image, self._paused_image = image, paused_icon_image(image)
        self.icon = pystray.Icon("Consiz", image, "Consiz — AI Context & Dictation", menu)
        pause.on_change(self._on_pause_changed)
        
        # Run detached in background thread
        def _ready(icon):
            icon.visible = True
            if self.welcome:
                try:
                    icon.notify(self.welcome, "Consiz is running")   # tells a first-time user where the app lives
                except Exception:
                    pass

        t = threading.Thread(target=lambda: self.icon.run(setup=_ready), daemon=True, name="TrayThread")
        t.start()

    def stop(self) -> None:
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
