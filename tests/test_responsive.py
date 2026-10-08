"""Windows adapt to the screen: small laptop screens, resizing, scrolling and centring (real Tk windows, briefly visible;
skipped without a display). The screen size is faked by replacing dpi.work_area_at."""
import time

import pytest

from consiz.platform.win32 import dpi

SMALL = (0, 0, 800, 480)                       # a tiny usable area: bigger windows must shrink to fit
BIG = (0, 0, 2560, 1400)


@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        from consiz.platform.win32 import popup as pm
        return pm._get_root()
    except tk.TclError:
        pytest.skip("no display available")


def _pump(root, seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def _screen(monkeypatch, area):
    monkeypatch.setattr(dpi, "work_area_at", lambda x, y: area)


# ---------------------------------------------------------------- popup
def test_popup_never_opens_bigger_than_a_small_screen(tk_root, monkeypatch):
    from consiz.platform.win32 import popup as pm
    _screen(monkeypatch, SMALL)
    ui = pm.PopupUI()
    ui.user_size = (3000, 3000)                                  # a size remembered from a huge monitor
    try:
        ui._show_at((700, 400), "Answer", "Chrome")
        _pump(tk_root)
        w, h = ui.window.winfo_width(), ui.window.winfo_height()
        x, y = ui.window.winfo_x(), ui.window.winfo_y()
        assert w <= SMALL[2] * 0.92 + 1 and h <= SMALL[3] * 0.92 + 1, (w, h)
        assert x >= 0 and y >= 0 and x + w <= SMALL[2] and y + h <= SMALL[3], (x, y, w, h)
    finally:
        ui.window.destroy()


def test_speech_bubbles_rewrap_when_the_window_is_resized(tk_root, monkeypatch):
    from consiz.platform.win32 import popup as pm
    _screen(monkeypatch, BIG)
    ui = pm.PopupUI()
    try:
        ui._show_at((100, 100), "Answer", "Chrome")
        _pump(tk_root, 0.3)
        ui._add_user("a fairly long question that needs wrapping when the window is narrow but not when it is wide")
        _pump(tk_root, 0.3)
        bubble = ui._bubbles[0]
        narrow = int(bubble.cget("wraplength"))
        ui.window.geometry(f"{ui.window.winfo_width() + 400}x{ui.window.winfo_height()}")
        _pump(tk_root, 0.5)
        wide = int(bubble.cget("wraplength"))
        assert wide > narrow + 200, f"the bubble kept its old width ({narrow} -> {wide})"
        ui._clear_chat()
        assert ui._bubbles == [], "no stale bubbles are kept after the chat is cleared"
    finally:
        ui.window.destroy()


def test_resizing_is_limited_to_the_screen(tk_root, monkeypatch):
    from consiz.platform.win32 import popup as pm
    _screen(monkeypatch, SMALL)
    ui = pm.PopupUI()
    try:
        ui._show_at((50, 50), "Answer", "Chrome")
        _pump(tk_root, 0.3)
        left, top, right, bottom = ui._area()
        assert (left, top, right, bottom) == SMALL
        # the grip handler is a closure; drive it through the real widgets like a user would
        grip = [w for w in _find(ui.window, "Label") if w.cget("text") == "⋰"][0]
        grip.event_generate("<Button-1>", x=1, y=1, rootx=300, rooty=300)
        grip.event_generate("<B1-Motion>", x=1, y=1, rootx=9000, rooty=9000)
        _pump(tk_root, 0.3)
        assert ui.user_size is not None
        assert ui.user_size[0] <= SMALL[2] - 20 and ui.user_size[1] <= SMALL[3] - 20, ui.user_size
    finally:
        ui.window.destroy()


# ---------------------------------------------------------------- Settings: fits, scrolls only when needed
def _find(widget, cls):
    found = []
    for c in widget.winfo_children():
        if c.winfo_class() == cls:
            found.append(c)
        found += _find(c, cls)
    return found


def _open_settings(tk_root, monkeypatch, area, tab):
    from consiz.platform.win32 import settings as st
    _screen(monkeypatch, area)
    st._OPEN["win"] = None
    st.show_settings_dialog(tk_root)
    win = st._OPEN["win"]
    book = _find(win, "TNotebook")[0]
    book.select(tab)
    _pump(tk_root, 0.6)
    return st, win


def test_settings_on_a_small_screen_shrinks_and_scrolls(tk_root, monkeypatch, tmp_path):
    from consiz import prefs
    monkeypatch.setattr(prefs, "STORE", tmp_path / "prefs.json")
    st, win = _open_settings(tk_root, monkeypatch, SMALL, tab=1)           # the Mouse tab is the tallest
    try:
        assert win.winfo_width() <= SMALL[2] * 0.9 + 1 and win.winfo_height() <= SMALL[3] * 0.9 + 1
        bars = [b for b in _find(win, "TScrollbar") if b.winfo_ismapped()]
        assert bars, "the tab needs a scroll bar when it does not fit"
    finally:
        st._OPEN["win"] = None
        win.destroy()


def test_settings_on_a_big_screen_needs_no_scroll_bar(tk_root, monkeypatch, tmp_path):
    from consiz import prefs
    monkeypatch.setattr(prefs, "STORE", tmp_path / "prefs.json")
    st, win = _open_settings(tk_root, monkeypatch, BIG, tab=0)
    try:
        assert not [b for b in _find(win, "TScrollbar") if b.winfo_ismapped()]
    finally:
        st._OPEN["win"] = None
        win.destroy()


def test_settings_notes_follow_the_window_width(tk_root, monkeypatch, tmp_path):
    from consiz import prefs
    monkeypatch.setattr(prefs, "STORE", tmp_path / "prefs.json")
    st, win = _open_settings(tk_root, monkeypatch, BIG, tab=1)
    try:
        notes = [n for n in st._NOTES if n.winfo_viewable()]            # only the tab that is showing
        assert notes
        before = int(notes[0].cget("wraplength"))
        win.geometry(f"{win.winfo_width() + 300}x{win.winfo_height()}")
        _pump(tk_root, 0.6)
        assert int(notes[0].cget("wraplength")) > before + 150, "explanatory text re-wraps to the wider window"
    finally:
        st._OPEN["win"] = None
        win.destroy()


# ---------------------------------------------------------------- sign-in window is centred on its screen
def test_sign_in_window_is_centred_inside_a_small_screen(tk_root, monkeypatch):
    from consiz.platform.win32.login import LoginUI
    _screen(monkeypatch, SMALL)
    ui = LoginUI()
    ui._build()
    try:
        _pump(tk_root, 0.3)
        x, y, w, h = ui.window.winfo_x(), ui.window.winfo_y(), ui.window.winfo_width(), ui.window.winfo_height()
        assert x >= 0 and y >= 0 and x + w <= SMALL[2] and y + h <= SMALL[3], (x, y, w, h)
        assert abs((x + w / 2) - SMALL[2] / 2) < 30, "horizontally centred"
    finally:
        ui.window.destroy()
