"""Nothing selected: a middle CLICK goes back to the app (T-01); the keyboard hotkey offers PC mode instead."""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows popup flow")

import main  # noqa: E402
from consiz import llm  # noqa: E402
from consiz.models import CapturedContext, CaptureMethod  # noqa: E402


class FakePopup:
    def __init__(self):
        self.opened, self.results = [], []

    def open_pc_chat(self, at=None, note=""):
        self.opened.append(note)

    def show_result(self, res):
        self.results.append(res)


@pytest.fixture
def popup(monkeypatch):
    p = FakePopup()
    monkeypatch.setattr(main, "POPUP", p)
    monkeypatch.setattr(main, "_login_needed", lambda: False)
    main._LOGIN_PROMPTED_AT[0] = 0.0
    return p


def _capture_returns(monkeypatch, text):
    import consiz.capture as cap
    monkeypatch.setattr(cap, "capture", lambda: CapturedContext("Notepad.exe", CaptureMethod.TEXT_SELECTION, text))


def test_middle_click_with_nothing_selected_is_handed_back_to_the_app(monkeypatch, popup):
    _capture_returns(monkeypatch, "")
    monkeypatch.setattr(main, "_pc_mode_consent", lambda: pytest.fail("a plain click must never ask for anything"))
    assert main.on_trigger("middle-click") == "passthrough"
    assert popup.opened == [] and popup.results == []                  # no popup, no error: the click just works


def test_hotkey_with_nothing_selected_opens_pc_chat_when_allowed(monkeypatch, popup):
    _capture_returns(monkeypatch, "")
    monkeypatch.setattr(main, "_pc_mode_consent", lambda: True)
    assert main.on_trigger("hotkey") is None
    assert popup.opened and "Nothing was selected" in popup.opened[0] and popup.results == []


def test_hotkey_with_nothing_selected_and_declined_shows_the_normal_message(monkeypatch, popup):
    _capture_returns(monkeypatch, "")
    monkeypatch.setattr(main, "_pc_mode_consent", lambda: False)
    main.on_trigger("hotkey")
    assert popup.opened == [] and len(popup.results) == 1 and popup.results[0].error is not None


def test_real_selection_is_not_hijacked(monkeypatch, popup):
    _capture_returns(monkeypatch, "Photosynthesis turns light into sugar.")
    monkeypatch.setattr(main, "_pc_mode_consent", lambda: pytest.fail("must not ask"))
    monkeypatch.setattr(main, "process", lambda ctx: "RESULT")
    assert main.on_trigger("middle-click") is None
    assert popup.opened == [] and popup.results == ["RESULT"]


def test_signed_out_clicks_do_not_nag_with_the_login_window(monkeypatch, popup):
    import time
    from consiz import auth
    monkeypatch.setattr(auth, "enabled", lambda: True)
    monkeypatch.setattr(auth, "signed_in", lambda: False)
    main._LOGIN_PROMPTED_AT[0] = time.time()                           # we asked a moment ago
    monkeypatch.setattr(main, "_login_needed", lambda: pytest.fail("must not reopen the sign-in window"))
    assert main.on_trigger("middle-click") == "passthrough"


def test_selection_chat_points_pc_questions_to_pc_mode():
    msgs = llm.chat_messages("some text", "- answer", [], "what is open in my Chrome?")
    assert "Ctrl+Alt+A" in msgs[-1]["content"] and "Ask about my PC" in msgs[-1]["content"]
