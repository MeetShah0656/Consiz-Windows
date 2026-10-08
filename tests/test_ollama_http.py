"""Offline mode talks to Ollama's local HTTP API directly (no Python package). Tested against a tiny fake Ollama server,
so the real network code runs: streaming, picture dropping, the 'thinking not supported' retry, errors, Stop."""
import http.server
import json
import threading
import time

import pytest

from consiz import llm
from consiz.config import CONFIG


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json(200, {"models": [{"name": m} for m in self.server.models]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self.server.requests.append(body)
        if body["model"] not in self.server.models:
            return self._json(404, {"error": f"model '{body['model']}' not found"})
        if "think" in body and self.server.reject_think:
            return self._json(400, {"error": f"\"{body['model']}\" does not support thinking"})
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for piece in self.server.pieces:
            self.wfile.write((json.dumps({"message": {"role": "assistant", "content": piece}, "done": False}) + "\n").encode())
            self.wfile.flush()
        if self.server.hang:                                  # a slow model: wait until the client hangs up
            for _ in range(300):
                time.sleep(0.02)
                try:
                    self.wfile.write(b"\n")
                    self.wfile.flush()
                except OSError:
                    self.server.client_left = True
                    return
            return
        self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())


@pytest.fixture
def ollama(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.models, srv.pieces, srv.requests = ["gemma4:e4b"], ["- hello ", "from ", "Ollama"], []
    srv.reject_think, srv.hang, srv.client_left = False, False, False
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(CONFIG, "ollama_host", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setattr(CONFIG, "ollama_model", "gemma4:e4b")
    monkeypatch.setattr(CONFIG, "provider", "ollama")
    llm.use_token(None)
    yield srv
    llm.use_token(None)
    srv.shutdown()
    srv.server_close()


MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]


def test_health_reports_model_present_missing_and_not_running(ollama, monkeypatch):
    assert llm._health_ollama() == (True, "Ollama · gemma4:e4b")
    ollama.models = ["llama3.2:3b"]
    ok, msg = llm._health_ollama()
    assert not ok and "ollama pull gemma4:e4b" in msg
    monkeypatch.setattr(CONFIG, "ollama_host", "http://127.0.0.1:9")            # nothing listens there
    ok, msg = llm._health_ollama()
    assert not ok and "ollama serve" in msg


def test_streams_a_chat(ollama):
    assert "".join(llm._stream_ollama_messages(MSGS)) == "- hello from Ollama"
    assert ollama.requests[0]["model"] == "gemma4:e4b" and ollama.requests[0]["stream"] is True


def test_pictures_are_not_sent_to_the_text_only_model(ollama):
    msgs = [{"role": "user", "content": [{"type": "text", "text": "what is this"},
                                         {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}]}]
    list(llm._stream_ollama_messages(msgs))
    sent = json.dumps(ollama.requests[0]["messages"])
    assert "AAAA" not in sent and "image_url" not in sent and "cannot read pictures" in sent


def test_a_model_without_thinking_support_is_asked_again_without_it(ollama):
    ollama.reject_think = True
    assert "".join(llm._stream_ollama_messages(MSGS)) == "- hello from Ollama"
    assert len(ollama.requests) == 2 and "think" in ollama.requests[0] and "think" not in ollama.requests[1]


def test_unknown_model_is_a_clear_error(ollama, monkeypatch):
    monkeypatch.setattr(CONFIG, "ollama_model", "nope:1b")
    with pytest.raises(llm.LLMError, match="not found"):
        list(llm._stream_ollama_messages(MSGS))


def test_ollama_not_running_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(CONFIG, "ollama_host", "http://127.0.0.1:9")
    with pytest.raises(llm.LLMError, match="ollama serve"):
        list(llm._stream_ollama_messages(MSGS))


def test_stop_cancels_an_offline_answer_and_hangs_up(ollama):
    ollama.hang = True
    tok = llm.CancelToken()
    got, errors = [], []

    def worker():
        llm.use_token(tok)
        try:
            for piece in llm._stream_ollama_messages(MSGS):
                got.append(piece)
        except BaseException as e:                                  # noqa: BLE001
            errors.append(e)

    th = threading.Thread(target=worker)
    th.start()
    deadline = time.time() + 3
    while len(got) < 3 and time.time() < deadline:
        time.sleep(0.01)
    tok.cancel()
    th.join(3)
    assert not th.is_alive() and len(errors) == 1 and isinstance(errors[0], llm.Cancelled)
    deadline = time.time() + 3
    while not ollama.client_left and time.time() < deadline:
        time.sleep(0.02)
    assert ollama.client_left, "Stop must hang up on Ollama so the local model stops generating"


def test_whole_chain_cloud_down_then_offline_over_real_http(ollama, monkeypatch):
    """The server is 'down' (typed error), Ollama answers over HTTP, and the user is told it was offline."""
    monkeypatch.setattr(CONFIG, "provider", "openrouter")
    monkeypatch.setattr(llm, "_server_url", lambda: "http://srv")
    def server_down(_messages):
        raise llm.LLMUnavailable("down")
        yield                                                       # makes this a generator, like the real stream

    monkeypatch.setattr(llm, "_stream_openrouter_messages", server_down)
    from consiz import prefs
    monkeypatch.setattr(prefs, "get", lambda key, default=None: default)
    llm._LOCAL.note = ""
    assert "".join(llm.stream_messages(MSGS)) == "- hello from Ollama"
    assert "offline" in llm.take_note()


def test_task_based_stream_uses_the_same_path(ollama):
    assert "".join(llm._stream_ollama("answer", "What is 2+2?")) == "- hello from Ollama"
    assert "What is 2+2?" in json.dumps(ollama.requests[0]["messages"])
