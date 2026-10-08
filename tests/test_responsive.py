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
        grip = [w for w in _find(ui.window, "Label") if w.cget("text") == "◢"][0]
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


# ---------------------------------------------------------------- the answer window resizes from every edge and corner
def test_edges_and_corners_are_found_from_the_window_borders():
    from consiz.platform.win32.popup import edges_at
    assert edges_at(0, 100, 500, 400, 7) == "l"
    assert edges_at(499, 100, 500, 400, 7) == "r"
    assert edges_at(250, 0, 500, 400, 7) == "t"
    assert edges_at(250, 399, 500, 400, 7) == "b"
    assert edges_at(2, 3, 500, 400, 7) == "lt"
    assert edges_at(498, 3, 500, 400, 7) == "rt"
    assert edges_at(2, 398, 500, 400, 7) == "lb"
    assert edges_at(498, 398, 500, 400, 7) == "rb"
    assert edges_at(250, 200, 500, 400, 7) == ""


def test_dragging_an_edge_moves_only_that_edge():
    from consiz.platform.win32.popup import resized_box
    area, small = (0, 0, 2000, 1200), (300, 250)
    box = (400, 300, 500, 400)
    assert resized_box(box, "r", 100, 50, small, area) == (400, 300, 600, 400)          # wider, nothing else moves
    assert resized_box(box, "b", 100, 50, small, area) == (400, 300, 500, 450)
    assert resized_box(box, "l", -100, 50, small, area) == (300, 300, 600, 400)         # left edge out: x moves, right edge stays
    assert resized_box(box, "t", 20, -80, small, area) == (400, 220, 500, 480)
    assert resized_box(box, "lt", -50, -50, small, area) == (350, 250, 550, 450)
    assert resized_box(box, "rb", 10, 10, small, area) == (400, 300, 510, 410)


def test_dragging_cannot_make_the_window_tiny_or_leave_the_screen():
    from consiz.platform.win32.popup import resized_box
    area, small = (0, 0, 1000, 800), (300, 250)
    box = (400, 300, 500, 400)
    x, y, w, h = resized_box(box, "l", 900, 0, small, area)                             # dragged far to the right
    assert w == 300 and x + w == 900, (x, w)                                            # stops at the minimum, right edge fixed
    x, y, w, h = resized_box(box, "t", 0, 900, small, area)
    assert h == 250 and y + h == 700
    x, y, w, h = resized_box(box, "rb", 5000, 5000, small, area)                        # dragged off the screen
    assert x + w == 1000 and y + h == 800
    x, y, w, h = resized_box(box, "lt", -5000, -5000, small, area)
    assert x == 0 and y == 0 and x + w == 900 and y + h == 700


def _drag(widget, start, end):
    widget.event_generate("<Button-1>", x=1, y=1, rootx=start[0], rooty=start[1])
    widget.event_generate("<B1-Motion>", x=1, y=1, rootx=end[0], rooty=end[1])
    widget.event_generate("<ButtonRelease-1>", x=1, y=1, rootx=end[0], rooty=end[1])


def test_the_user_can_drag_each_side_of_the_real_window(tk_root, monkeypatch, tmp_path):
    from consiz import prefs
    from consiz.platform.win32 import popup as pm
    _screen(monkeypatch, BIG)
    monkeypatch.setattr(prefs, "STORE", tmp_path / "prefs.json")             # the dragged size is saved: never to the real file
    ui = pm.PopupUI()
    ui.user_size = None
    try:
        ui._show_at((900, 400), "Answer", "Chrome")
        _pump(tk_root, 0.4)
        win = ui.window
        x, y, w, h = win.winfo_x(), win.winfo_y(), win.winfo_width(), win.winfo_height()
        edge = pm.RESIZE_BAND // 2
        # right edge: press on the plain border strip and pull it 150 px outwards
        _drag(win, (x + w - edge, y + h // 2), (x + w - edge + 150, y + h // 2))
        _pump(tk_root, 0.2)
        assert win.winfo_width() == w + 150 and win.winfo_x() == x, (w, win.winfo_width())
        # left edge: the window grows to the left and its right edge stays put
        x2, w2 = win.winfo_x(), win.winfo_width()
        _drag(win, (x2 + edge, y + h // 2), (x2 + edge - 120, y + h // 2))
        _pump(tk_root, 0.2)
        assert win.winfo_width() == w2 + 120 and win.winfo_x() + win.winfo_width() == x2 + w2
        # bottom-right corner
        x3, y3, w3, h3 = win.winfo_x(), win.winfo_y(), win.winfo_width(), win.winfo_height()
        _drag(win, (x3 + w3 - edge, y3 + h3 - edge), (x3 + w3 - edge + 40, y3 + h3 - edge + 60))
        _pump(tk_root, 0.2)
        assert (win.winfo_width(), win.winfo_height()) == (w3 + 40, h3 + 60)
        assert ui.user_size == (w3 + 40, h3 + 60), "the new size is remembered"
        # the chat text re-flows to the new width
        chat_w = ui.chat.winfo_width()
        assert chat_w > w - 60, chat_w
        assert prefs.get("popup_size") is not None, "saved to the (temporary) prefs when the drag ended"
    finally:
        ui.window.destroy()


def test_a_click_inside_the_window_does_not_start_a_resize(tk_root, monkeypatch, tmp_path):
    from consiz import prefs
    from consiz.platform.win32 import popup as pm
    _screen(monkeypatch, BIG)
    monkeypatch.setattr(prefs, "STORE", tmp_path / "prefs.json")
    ui = pm.PopupUI()
    ui.user_size = None
    try:
        ui._show_at((900, 400), "Answer", "Chrome")
        _pump(tk_root, 0.4)
        win = ui.window
        x, y, w, h = win.winfo_x(), win.winfo_y(), win.winfo_width(), win.winfo_height()
        _drag(win, (x + w // 2, y + h // 2), (x + w // 2 + 200, y + h // 2 + 200))
        _pump(tk_root, 0.2)
        assert (win.winfo_width(), win.winfo_height()) == (w, h)
        assert ui.user_size is None
    finally:
        ui.window.destroy()
