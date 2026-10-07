"""Middle-click with nothing selected: offer PC mode (with permission) instead of a dead-end error."""
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
    return p


def _capture_returns(monkeypatch, text):
    import consiz.capture as cap
    monkeypatch.setattr(cap, "capture", lambda: CapturedContext("Notepad.exe", CaptureMethod.TEXT_SELECTION, text))


def test_nothing_selected_opens_pc_chat_when_allowed(monkeypatch, popup):
    _capture_returns(monkeypatch, "")
    monkeypatch.setattr(main, "_pc_mode_consent", lambda: True)
    main.on_trigger("middle-click")
    assert popup.opened and "Nothing was selected" in popup.opened[0] and popup.results == []


def test_nothing_selected_and_declined_shows_the_normal_message(monkeypatch, popup):
    _capture_returns(monkeypatch, "")
    monkeypatch.setattr(main, "_pc_mode_consent", lambda: False)
    main.on_trigger("middle-click")
    assert popup.opened == [] and len(popup.results) == 1 and popup.results[0].error is not None


def test_real_selection_is_not_hijacked(monkeypatch, popup):
    _capture_returns(monkeypatch, "Photosynthesis turns light into sugar.")
    monkeypatch.setattr(main, "_pc_mode_consent", lambda: pytest.fail("must not ask"))
    monkeypatch.setattr(main, "process", lambda ctx: "RESULT")
    main.on_trigger("middle-click")
    assert popup.opened == [] and popup.results == ["RESULT"]


def test_selection_chat_points_pc_questions_to_pc_mode():
    msgs = llm.chat_messages("some text", "- answer", [], "what is open in my Chrome?")
    assert "Ctrl+Alt+A" in msgs[-1]["content"] and "Ask about my PC" in msgs[-1]["content"]
