"""App-side behaviour when talking to the Consiz backend: cold-start retry and sign-in expiry."""
import pytest

from consiz import llm


class _Resp:
    def __init__(self, status, lines=()):
        self.status_code = status
        self._lines = list(lines)
        self.text = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        return iter(self._lines)

    def json(self):
        return {"detail": "x"}


OK_LINES = [b'data: {"choices":[{"delta":{"content":"hello"}}]}', b"data: [DONE]"]


@pytest.fixture(autouse=True)
def server_mode(monkeypatch):
    monkeypatch.setattr(llm, "_server_url", lambda: "http://srv")
    monkeypatch.setattr(llm, "_api_key", lambda: "tok")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def _run():
    return list(llm._openrouter_sse([{"role": "user", "content": "hi"}], llm._REASONING_OFF, 100))


def test_retries_while_server_wakes_up(monkeypatch):
    seq = iter([_Resp(503), _Resp(502), _Resp(200, OK_LINES)])
    monkeypatch.setattr(llm._SESSION, "post", lambda *a, **k: next(seq))
    assert ("hello", None) in _run()


def test_gives_up_after_three_attempts(monkeypatch):
    monkeypatch.setattr(llm._SESSION, "post", lambda *a, **k: _Resp(503))
    with pytest.raises(llm.LLMError):
        _run()


def test_rejected_token_means_sign_in_again(monkeypatch):
    from consiz import auth
    signed_out = []
    monkeypatch.setattr(auth, "sign_out", lambda: signed_out.append(1))
    monkeypatch.setattr(llm._SESSION, "post", lambda *a, **k: _Resp(401))
    with pytest.raises(llm.SignInRequired):
        _run()
    assert signed_out == [1]


def test_connection_error_retries_then_works(monkeypatch):
    calls = {"n": 0}

    def post(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise llm.requests.exceptions.ConnectionError("waking")
        return _Resp(200, OK_LINES)

    monkeypatch.setattr(llm._SESSION, "post", post)
    assert ("hello", None) in _run()

