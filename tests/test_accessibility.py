"""Accessibility (T-17): keyboard use, Windows' text size, high contrast, names for screen readers. Real Tk windows
(skipped without a display). What Tk cannot do for screen readers is written down in docs/ACCESSIBILITY.md."""
import ctypes
import subprocess
import sys
import time

import pytest

from consiz import prefs
from consiz.platform.win32 import a11y, dpi

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        from consiz.platform.win32 import popup as pm
        return pm._get_root()
    except tk.TclError:
        pytest.skip("no display available")


def _pump(root, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def _text_of(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(200)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 200)
    return buf.value


# ---------------------------------------------------------------- Windows settings are read
def test_text_size_comes_from_windows_and_is_kept_in_a_sensible_range(monkeypatch):
    monkeypatch.setattr(a11y, "_cache", {})
    monkeypatch.setenv("CONSIZ_TEXT_SCALE", "1.5")
    assert a11y.text_scale() == 1.5
    monkeypatch.setattr(a11y, "_cache", {})
    monkeypatch.setenv("CONSIZ_TEXT_SCALE", "9")
    assert a11y.text_scale() == 2.25, "never more than Windows' own maximum"
    monkeypatch.setattr(a11y, "_cache", {})
    monkeypatch.setenv("CONSIZ_TEXT_SCALE", "0.2")
    assert a11y.text_scale() == 1.0, "never smaller than normal"


def test_text_size_makes_fixed_sizes_grow_with_the_fonts(monkeypatch):
    monkeypatch.delenv("CONSIZ_UI_SCALE", raising=False)
    monkeypatch.setitem(dpi._state, "scale", 1.25)
    monkeypatch.setattr(a11y, "_cache", {"text_scale": 1.0})
    normal = dpi.px(100)
    monkeypatch.setattr(a11y, "_cache", {"text_scale": 1.5})
    assert dpi.px(100) == round(normal * 1.5)


def test_high_contrast_uses_the_windows_theme_colours():
    code = ("from consiz.platform.win32 import theme as t; "
            "print(t.CREAM_50, t.MAROON_900, t.MAROON_700, t.SELECT_BG, t.SELECT_FG)")
    on = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**__import__("os").environ, "CONSIZ_HIGH_CONTRAST": "1"})
    off = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**__import__("os").environ, "CONSIZ_HIGH_CONTRAST": "0"})
    assert on.stdout.split() == ["SystemWindow", "SystemWindowText", "SystemHighlight", "SystemHighlight", "SystemHighlightText"], on.stderr
    assert off.stdout.split()[0] == "#FFFCF6", "normal colours when no high-contrast theme is on"


def test_the_screen_reader_check_does_not_crash():
    assert a11y.screen_reader_running() in (True, False)
    assert a11y.high_contrast() in (True, False)


def test_the_answer_window_takes_the_focus_only_when_asked_or_a_screen_reader_runs(monkeypatch):
    monkeypatch.setattr(a11y, "screen_reader_running", lambda: False)
    assert a11y.popup_takes_focus() is False
    prefs.set("popup_takes_focus", True)
    assert a11y.popup_takes_focus() is True
    prefs.set("popup_takes_focus", None)
    monkeypatch.setattr(a11y, "screen_reader_running", lambda: True)
    assert a11y.popup_takes_focus() is True, "automatic while a screen reader runs"
    prefs.set("popup_takes_focus", False)
    assert a11y.popup_takes_focus() is False, "the person's own choice wins"


# ---------------------------------------------------------------- the answer window by keyboard
def test_every_button_can_be_tabbed_to_and_pressed_with_enter_or_space(tk_root):
    from consiz.platform.win32 import popup as pm
    ui = pm.PopupUI()
    try:
        ui._show_at((100, 100), "Answer", "x")
        _pump(tk_root)
        for label in ("Send ➤", "Copy all", "Save as text", "↺ New chat", "—", "✕", "🎙"):
            widget = next(w for w in _all(ui.window) if _text(w) == label)
            assert str(widget.cget("takefocus")) in ("1", "True", "true"), label
        # Enter and Space on the Copy all button run its action (it changes its own text to "Copied ✓")
        copy = next(w for w in _all(ui.window) if _text(w) == "Copy all")
        copy.focus_set()
        copy.event_generate("<Return>")
        _pump(tk_root, 0.1)
        assert copy.cget("text") == "Copied ✓"
        copy.config(text="Copy all")
        copy.event_generate("<space>")
        _pump(tk_root, 0.1)
        assert copy.cget("text") == "Copied ✓"
    finally:
        ui.window.destroy()


def _all(widget):
    out = []
    for c in widget.winfo_children():
        out.append(c)
        out += _all(c)
    return out


def _text(w):
    try:
        return str(w.cget("text"))
    except Exception:
        return None


def test_tab_goes_from_the_question_box_through_send_and_the_answer_to_the_header(tk_root):
    from consiz.platform.win32 import popup as pm
    ui = pm.PopupUI()
    try:
        ui._show_at((100, 100), "Answer", "x")
        _pump(tk_root)
        order, w = [], ui.entry
        for _ in range(40):
            order.append(w)
            w = w.tk_focusNext()
            if w is None or w is ui.entry:
                break
        names = [_text(x) or x.winfo_class() for x in order]
        assert names[0] == "Text" and ui.entry is order[0], "typing comes first"
        assert names.index("Send ➤") < names.index("Copy all") < names.index("↺ New chat") < names.index("✕"), names
        for label in ("Send ➤", "Copy all", "Save as text", "↺ New chat", "—", "✕"):
            assert label in names, f"{label} cannot be reached with Tab"
    finally:
        ui.window.destroy()


def test_buttons_and_windows_have_names_a_screen_reader_can_read(tk_root):
    from consiz.platform.win32 import popup as pm
    ui = pm.PopupUI()
    try:
        ui._show_at((100, 100), "Answer", "x")
        _pump(tk_root)
        assert _text_of(ui._hwnd()) == "Consiz answer"
        assert _text_of(ui.send_btn.winfo_id()) == "Send"
        assert _text_of(ui.entry.winfo_id()) == "Your question"
        ui._set_chat_busy(True)
        assert _text_of(ui.send_btn.winfo_id()) == "Stop", "the name follows the button"
        ui._set_chat_busy(False)
        assert _text_of(ui.send_btn.winfo_id()) == "Send"
    finally:
        ui.window.destroy()


def test_the_window_asks_for_the_keyboard_focus_only_when_the_setting_says_so(tk_root, monkeypatch):
    from consiz.platform.win32 import popup as pm
    monkeypatch.setattr(a11y, "screen_reader_running", lambda: False)
    ui = pm.PopupUI()
    try:
        ui._show_at((100, 100), "Answer", "x")
        assert ui._focus_after_show is False
        prefs.set("popup_takes_focus", True)
        ui._show_at((100, 100), "Answer", "x")
        assert ui._focus_after_show is True
    finally:
        ui.window.destroy()


# ---------------------------------------------------------------- bigger text: nothing is cut off
@pytest.fixture
def bigger_text(tk_root):
    """Windows 'Text size' at 150 %: fonts and fixed sizes grow together, then everything is put back."""
    import consiz.platform.win32.login      # noqa: F401  - modules compute some sizes when first imported:
    import consiz.platform.win32.onboarding  # noqa: F401  they must be imported BEFORE the text size is changed
    import consiz.platform.win32.popup      # noqa: F401
    import consiz.platform.win32.settings   # noqa: F401
    old_scaling = float(tk_root.tk.call("tk", "scaling"))
    old_cache = dict(a11y._cache)
    a11y._cache["text_scale"] = 1.5
    tk_root.tk.call("tk", "scaling", old_scaling * 1.5)
    yield 1.5
    tk_root.tk.call("tk", "scaling", old_scaling)
    a11y._cache.clear()
    a11y._cache.update(old_cache)


def _clipped(win):
    """Widgets that reach past the window's edge."""
    win.update_idletasks()
    right, bottom = win.winfo_rootx() + win.winfo_width(), win.winfo_rooty() + win.winfo_height()
    bad = []
    for w in _all(win):
        if w.winfo_ismapped() and w.winfo_width() > 1:
            if w.winfo_rootx() + w.winfo_width() > right + 1 or w.winfo_rooty() + w.winfo_height() > bottom + 1:
                bad.append((w.winfo_class(), _text(w)))
    return bad


def test_the_sign_in_window_fits_its_text_at_150_percent_text_size(tk_root, bigger_text, monkeypatch):
    monkeypatch.setattr(dpi, "work_area_at", lambda x, y: (0, 0, 2560, 1400))
    from consiz.platform.win32.login import LoginUI
    ui = LoginUI()
    ui._build()
    try:
        _pump(tk_root, 0.5)
        assert _clipped(ui.window) == []
    finally:
        ui.window.destroy()


def test_the_answer_window_grows_its_text_and_stays_on_the_screen_at_150_percent(tk_root, bigger_text, monkeypatch):
    area = (0, 0, 1536, 864)
    monkeypatch.setattr(dpi, "work_area_at", lambda x, y: area)
    from consiz.platform.win32 import popup as pm
    ui = pm.PopupUI()
    ui.user_size = None
    try:
        ui._show_at((700, 400), "Answer", "x")
        ui._begin_ai()
        for line in ("- First bullet with a few words.", "- Second bullet that is a little longer than the first one."):
            ui._append(line)
        _pump(tk_root, 0.6)
        w, h, x, y = ui.window.winfo_width(), ui.window.winfo_height(), ui.window.winfo_x(), ui.window.winfo_y()
        assert x >= 0 and y >= 0 and x + w <= area[2] and y + h <= area[3], (x, y, w, h)
        assert _clipped(ui.window) == []
    finally:
        ui.window.destroy()
