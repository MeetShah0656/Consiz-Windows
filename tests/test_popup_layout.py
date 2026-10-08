"""Popup layout: the Explain popup and the PC chat share one window, so they must size themselves the same sensible way.
Real (briefly visible, non-focus-stealing) Tk window; skipped when there is no display."""
import time

import pytest


@pytest.fixture
def popup():
    tk = pytest.importorskip("tkinter")
    try:
        from consiz.platform.win32 import popup as pm
        ui = pm.PopupUI()
        pm._get_root()
    except tk.TclError:
        pytest.skip("no display available")
    yield pm, ui
    if ui.window is not None:
        ui.window.destroy()


def _pump(pm, seconds=0.8):
    end = time.time() + seconds
    while time.time() < end:
        pm._get_root().update()
        time.sleep(0.01)


def _fully_visible(ui):
    """True when the chat needs no scrolling."""
    top, bottom = ui.chat.yview()
    return top == 0.0 and bottom == 1.0


def test_lines_added_the_instant_the_window_opens_do_not_collapse_it(popup):
    """Errors and file/table results append text in the same tick that opens the window: it used to become 1 px wide."""
    pm, ui = popup
    pm._dispatch(ui._show_at, (60, 60), "Nothing selected", "Chrome")
    for line in ("No text was selected.", "Select some text first, then press the middle mouse button."):
        pm._dispatch(ui._append, line)
    _pump(pm)
    assert ui.window.winfo_width() >= 300 and ui.window.winfo_height() >= 250
    assert _fully_visible(ui)


def test_pc_chat_is_as_tall_as_its_questions_not_the_whole_screen(popup):
    pm, ui = popup
    ui.open_pc_chat((60, 60))
    _pump(pm)
    from consiz.platform.win32 import dpi
    _l, top, _r, bottom = dpi.work_area_at(60, 60)
    assert ui.window.winfo_height() < (bottom - top) * 0.65, "it used to open at the maximum height with a big empty area"
    assert _fully_visible(ui), "all five starter questions are visible without scrolling"
    empty = ui.chat.winfo_height() - int(ui.chat.count("1.0", "end", "update", "ypixels"))
    assert empty < dpi.px(80), f"too much empty space under the questions ({empty}px)"


def test_a_long_conversation_grows_then_scrolls_instead_of_leaving_the_screen(popup):
    pm, ui = popup
    pm._dispatch(ui._show_at, (60, 60), "Answer", "Chrome")
    for i in range(120):
        pm._dispatch(ui._append, f"- bullet number {i} with a few extra words so it is not tiny")
    _pump(pm, 1.5)
    from consiz.platform.win32 import dpi
    _l, top, _r, bottom = dpi.work_area_at(60, 60)
    assert ui.window.winfo_height() <= int((bottom - top) * 0.65) + 2
    assert not _fully_visible(ui), "past the cap the chat scrolls"


def test_new_chat_in_pc_mode_shows_the_pc_screen_again(popup):
    pm, ui = popup
    ui.open_pc_chat((60, 60), note="Nothing was selected, so this is Ask about my PC.")
    _pump(pm)
    ui._add_user("What is slowing my PC down?")
    ui.new_chat()
    _pump(pm)
    shown = ui.chat.get("1.0", "end")
    assert "What is slowing my PC down?" in shown            # a starter question is back
    assert "text you selected" not in shown and ui.title_lbl.cget("text") == "Ask about my PC"
    assert "Nothing was selected" not in shown, "the one-time note is not repeated"
    assert "selected text" not in ui.meta_lbl.cget("text")


def test_new_chat_for_selected_text_still_says_so(popup):
    pm, ui = popup
    pm._dispatch(ui._show_at, (60, 60), "Explained", "Chrome")
    _pump(pm, 0.3)
    ui.mode = "selection"
    ui.new_chat()
    assert "text you selected" in ui.chat.get("1.0", "end")


def test_people_see_plain_words_not_internal_names():
    from consiz.platform.win32 import popup as pm
    assert pm._type_label("TEXT_SELECTION") == "Selected text" and pm._type_label("CSV_DATA") == "Table"
    assert pm._type_label("VOICE (Hindi) · text_selection") == "VOICE (Hindi) · text_selection", "unknown values pass through"
    assert pm._error_title("NO_CONTEXT_FOUND") == "Nothing selected" and pm._error_title("BACKEND_UNAVAILABLE") == "AI not reachable"
    assert pm._error_title("SOMETHING_NEW") == "SOMETHING_NEW"
    from consiz.models import ErrorState
    for state in ErrorState:                                    # a new error state must get a friendly title too
        assert pm._error_title(state.value) != state.value, state
