"""Stop button / cancel (T-05) and Pause (T-10). The AI provider is faked; the popup test uses a real hidden Tk window."""
import ctypes
import threading
import time

import pytest
import requests

from consiz import llm, pause
from consiz.platform.win32 import fullscreen, mousegate


# ---------------------------------------------------------------- fakes
class FakeResp:
    """A streaming HTTP response. `hang=True` blocks after the first chunk until close() is called, like a slow AI."""

    def __init__(self, lines=(), status=200, hang=False, body=None):
        self.status_code, self._lines, self.hang, self.closed = status, list(lines), hang, False
        self._body = body or {}
        self.text = str(self._body)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True

    def json(self):
        return self._body

    def close(self):
        self.closed = True

    def iter_lines(self):
        for ln in self._lines:
            if self.closed:
                raise requests.exceptions.ChunkedEncodingError("connection closed")
            yield ln
        while self.hang:
            if self.closed:
                raise requests.exceptions.ChunkedEncodingError("connection closed")
            time.sleep(0.01)


def _chunk(text):
    return b'data: {"choices":[{"delta":{"content":"%s"}}]}' % text.encode()


@pytest.fixture
def direct(monkeypatch):
    monkeypatch.setattr(llm, "_server_url", lambda: "")
    monkeypatch.setattr(llm, "_api_key", lambda: "k")
    llm.use_token(None)
    yield
    llm.use_token(None)


def _drain(gen):
    return [p for p, _f in gen if p]


# ---------------------------------------------------------------- cancel token
def test_cancel_closes_the_open_connection_and_raises_cancelled(direct, monkeypatch):
    resp = FakeResp([_chunk("one "), _chunk("two ")], hang=True)
    monkeypatch.setattr(llm._SESSION, "post", lambda *a, **k: resp)
    tok = llm.CancelToken()
    llm.use_token(tok)
    got, errors = [], []

    def worker():
        llm.use_token(tok)
        try:
            for piece, _f in llm._openrouter_sse([{"role": "user", "content": "hi"}], llm._REASONING_OFF, 100):
                if piece:
                    got.append(piece)
        except BaseException as e:                              # noqa: BLE001
            errors.append(e)

    th = threading.Thread(target=worker)
    th.start()
    deadline = time.time() + 3
    while len(got) < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert got == ["one ", "two "]
    tok.cancel()
    th.join(3)
    assert not th.is_alive(), "the worker must stop at once, not wait for the AI"
    assert resp.closed, "the HTTP stream must be closed (that is what makes the server stop paying)"
    assert len(errors) == 1 and isinstance(errors[0], llm.Cancelled)


def test_no_retry_after_cancel(monkeypatch):
    monkeypatch.setattr(llm, "_server_url", lambda: "http://server")
    monkeypatch.setattr(llm, "_api_key", lambda: "tok")
    calls = []

    def post(*a, **k):
        calls.append(1)
        tok.cancel()                                           # Stop pressed while connecting
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(llm._SESSION, "post", post)
    tok = llm.CancelToken()
    llm.use_token(tok)
    try:
        with pytest.raises(llm.Cancelled):
            _drain(llm._openrouter_sse([{"role": "user", "content": "hi"}], llm._REASONING_OFF, 100))
    finally:
        llm.use_token(None)
    assert len(calls) == 1


def test_stop_wakes_the_cold_start_wait(monkeypatch):
    """A sleeping server answers 503 and the app waits 6 s before retrying: Stop must not wait that long."""
    monkeypatch.setattr(llm, "_server_url", lambda: "http://server")
    monkeypatch.setattr(llm, "_api_key", lambda: "tok")
    monkeypatch.setattr(llm._SESSION, "post", lambda *a, **k: FakeResp(status=503, body={"detail": "waking"}))
    tok = llm.CancelToken()
    threading.Timer(0.2, tok.cancel).start()
    llm.use_token(tok)
    t0 = time.time()
    try:
        with pytest.raises(llm.Cancelled):
            _drain(llm._openrouter_sse([{"role": "user", "content": "hi"}], llm._REASONING_OFF, 100))
    finally:
        llm.use_token(None)
    assert time.time() - t0 < 3


def test_a_cancelled_token_stops_the_second_call_of_a_two_step_answer(direct, monkeypatch):
    """PC mode asks the AI twice (READ, then answer). Cancelling during the permission box must stop call #2."""
    calls = []
    monkeypatch.setattr(llm._SESSION, "post", lambda *a, **k: calls.append(1) or FakeResp([_chunk("x")]))
    tok = llm.CancelToken()
    llm.use_token(tok)
    assert _drain(llm._openrouter_sse([{"role": "user", "content": "a"}], llm._REASONING_OFF, 100)) == ["x"]
    tok.cancel()
    with pytest.raises(llm.Cancelled):
        _drain(llm._openrouter_sse([{"role": "user", "content": "b"}], llm._REASONING_OFF, 100))
    assert len(calls) == 1


# ---------------------------------------------------------------- availability errors (used by the offline fallback)
@pytest.mark.parametrize("status,kind", [(500, llm.LLMUnavailable), (502, llm.LLMUnavailable), (503, llm.LLMUnavailable),
                                         (400, llm.LLMError), (429, llm.LLMError)])
def test_only_availability_failures_are_unavailable(direct, monkeypatch, status, kind):
    monkeypatch.setattr(llm._SESSION, "post", lambda *a, **k: FakeResp(status=status, body={"error": {"message": "x"}}))
    with pytest.raises(llm.LLMError) as e:
        _drain(llm._openrouter_sse([{"role": "user", "content": "hi"}], llm._REASONING_OFF, 100))
    assert isinstance(e.value, llm.LLMUnavailable) == (kind is llm.LLMUnavailable)


def test_unreachable_and_timeout_are_unavailable(direct, monkeypatch):
    for exc in (requests.exceptions.ConnectionError("no net"), requests.exceptions.ReadTimeout("slow")):
        def post(*a, _e=exc, **k):
            raise _e
        monkeypatch.setattr(llm._SESSION, "post", post)
        with pytest.raises(llm.LLMUnavailable):
            _drain(llm._openrouter_sse([{"role": "user", "content": "hi"}], llm._REASONING_OFF, 100))


# ---------------------------------------------------------------- pause
@pytest.fixture(autouse=True)
def _reset_pause():
    pause.set_paused(False)
    yield
    pause.set_paused(False)


def test_pause_state_and_listeners():
    seen = []
    pause.on_change(seen.append)
    assert pause.is_paused() is False
    pause.set_paused(True)
    pause.set_paused(True)                                     # no change, no second call
    assert pause.is_paused() is True and seen[-1:] == [True] and seen.count(True) == 1
    assert pause.toggle() is False and seen[-1] is False


def test_paused_gate_gives_every_click_back_to_the_app():
    gate = mousegate.MiddleGate()
    assert gate.down(1, 1, False, "chrome.exe", 1.0, paused=True) is mousegate.Act.PASS
    assert gate.up(1.05) is mousegate.Act.PASS                 # the release goes to the app too: no half-click
    assert gate.down(1, 1, False, "chrome.exe", 2.0) is mousegate.Act.SWALLOW      # active again


def test_fullscreen_detector_uses_the_windows_busy_states(monkeypatch):
    class Shell:
        def __init__(self, value, ok=0):
            self.value, self.ok = value, ok

        def SHQueryUserNotificationState(self, ref):
            ref._obj.value = self.value
            return self.ok

    class Win:
        def __init__(self, shell):
            self.shell32 = shell

    for state, expected in [(5, False), (1, False), (2, True), (3, True), (4, True)]:
        monkeypatch.setattr(ctypes, "windll", Win(Shell(state)), raising=False)
        assert fullscreen.foreground_is_fullscreen() is expected
    monkeypatch.setattr(ctypes, "windll", Win(Shell(2, ok=1)), raising=False)       # API failed: stay active
    assert fullscreen.foreground_is_fullscreen() is False


# ---------------------------------------------------------------- the popup (real, hidden Tk window)
@pytest.fixture
def popup():
    tk = pytest.importorskip("tkinter")
    try:
        from consiz.platform.win32 import popup as pm
        ui = pm.PopupUI()
        ui._build()
        ui.window.withdraw()
    except tk.TclError:
        pytest.skip("no display available")
    yield pm, ui
    ui.window.destroy()


def _pump(pm, seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        pm._get_root().update()
        time.sleep(0.01)


def test_stop_button_stops_and_drops_late_text(popup):
    pm, ui = popup
    ui._set_chat_busy(True)
    tok = ui._new_token()
    assert ui.send_btn.cget("text") == "■ Stop"
    ui._send_or_stop()                                         # the user clicks Stop
    assert tok.cancelled and ui._chat_busy is False and ui.send_btn.cget("text") == "Send ➤"
    ui._post(tok, ui._append, "late line from the stopped answer")
    _pump(pm)
    shown = ui.chat.get("1.0", "end")
    assert "late line" not in shown and "Stopped." in shown


def test_a_new_request_cancels_the_old_one_and_keeps_its_own_state(popup):
    pm, ui = popup
    old = ui._new_token()
    new = ui._new_token()
    assert old.cancelled and not new.cancelled
    ui._set_chat_busy(True)
    ui._end_run(old)                                           # the old worker finishing must not clear the new run
    assert ui._chat_busy is True
    ui._end_run(new)
    assert ui._chat_busy is False


def test_closing_the_window_cancels_the_answer(popup):
    pm, ui = popup
    tok = ui._new_token()
    ui._set_chat_busy(True)
    ui.hide()
    _pump(pm)
    assert tok.cancelled and ui._chat_busy is False


def test_followup_stream_stops_midway_and_is_not_remembered(popup):
    pm, ui = popup
    tok = ui._new_token()
    llm.use_token(tok)
    closed = []

    def stream():
        try:
            yield "- first bullet\n"
            tok.cancel()                                       # user presses Stop while the answer is streaming
            yield "- second bullet\n"
            yield "- third bullet\n"
        finally:
            closed.append(True)

    try:
        ui.show_followup("why?", stream())
    finally:
        llm.use_token(None)
    _pump(pm)
    assert ui.history == [], "a stopped answer must not enter the chat history"
    assert closed == [True], "the stream must be closed so the connection is released"
    assert "third bullet" not in ui.chat.get("1.0", "end")


# ---------------------------------------------------------------- tray menu: sub-menus must open to the right
def test_trigger_menu_labels_are_short_enough_to_open_on_the_right():
    """Windows flips a sub-menu to the left when it does not fit beside a tray menu at the screen edge (~470 px free at
    125 %). Long labels did exactly that; keep them short (the explanation lives in Settings > Mouse)."""
    from consiz.platform.win32 import mousegate, tray
    assert set(tray.TRIGGER_LABELS) == set(mousegate.MODES), "every trigger mode has a label"
    assert max(len(v) for v in tray.TRIGGER_LABELS.values()) <= 24
    assert all("(" not in v for v in tray.TRIGGER_LABELS.values())
