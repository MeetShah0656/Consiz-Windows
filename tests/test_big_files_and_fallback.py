"""T-07 (huge tables never freeze the app) and T-04 (server -> offline Ollama -> clear message)."""
import pytest

from consiz import deterministic as det
from consiz import llm, prefs


# ---------------------------------------------------------------- T-07
def _csv(tmp_path, rows):
    p = tmp_path / "big.csv"
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("id,amount,status\n")
        for i in range(rows):
            fh.write(f"{i},{i % 97},{'open' if i % 3 else 'closed'}\n")
    return str(p)


def test_small_table_is_untouched(tmp_path):
    res = det.analyze_csv(_csv(tmp_path, 40), is_path=True)
    assert res.row_count == 40 and not res.warnings
    assert "first rows only" not in det.format_numerical(res, "t.csv")


def test_huge_table_reads_only_the_first_rows_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(det, "MAX_ROWS", 50)
    res = det.analyze_csv(_csv(tmp_path, 300), is_path=True)
    assert res.row_count == 50
    assert any("first 50 rows" in w for w in res.warnings)
    assert res.computed_stats["shape"]["first_rows_only"] is True
    assert "first rows only" in det.format_numerical(res, "big.csv")        # the narrator is told too


def test_a_two_million_row_file_is_still_fast(tmp_path):
    import time
    path = _csv(tmp_path, 2_000_000)                                          # ~30 MB
    t0 = time.time()
    res = det.analyze_csv(path, is_path=True)
    assert res.row_count == det.MAX_ROWS
    assert time.time() - t0 < 20, "the reader must stop at MAX_ROWS instead of loading the whole file"


def test_giant_workbook_is_refused_with_a_helpful_message(monkeypatch):
    monkeypatch.setattr(det.os.path, "getsize", lambda p: 400 * 1024 * 1024)
    with pytest.raises(ValueError) as e:
        det.analyze_csv("C:/data/huge.xlsx", is_path=True)
    assert "too big" in str(e.value) and "Excel" in str(e.value)


def test_giant_pasted_selection_is_refused():
    with pytest.raises(ValueError):
        det.analyze_csv("x" * (det.MAX_PASTED_CHARS + 1), is_path=False)


# ---------------------------------------------------------------- T-04
@pytest.fixture
def offline(monkeypatch):
    """Ollama 'installed and running'; the offline fallback switched on."""
    monkeypatch.setattr(llm, "_health_ollama", lambda: (True, "Ollama"))
    monkeypatch.setattr(prefs, "get", lambda key, default=None: default)
    llm._LOCAL.note = ""


def _failing(exc, pieces=()):
    def gen():
        for p in pieces:
            yield p
        raise exc
    return gen()


def test_server_unreachable_falls_back_to_offline_with_a_note(offline):
    out = list(llm._with_offline_fallback(_failing(llm.LLMUnavailable("server down")), lambda: iter(["- offline ", "answer"])))
    assert out == ["- offline ", "answer"]
    note = llm.take_note()
    assert "offline" in note and "could not be reached" in note
    assert llm.take_note() == "", "the note is shown once"


def test_no_ollama_means_the_original_error_unchanged(monkeypatch):
    monkeypatch.setattr(llm, "_health_ollama", lambda: (False, "not running"))
    monkeypatch.setattr(prefs, "get", lambda key, default=None: default)
    with pytest.raises(llm.LLMUnavailable, match="server down"):
        list(llm._with_offline_fallback(_failing(llm.LLMUnavailable("server down")), lambda: iter(["never"])))


@pytest.mark.parametrize("exc", [llm.LLMError("Daily limit of 50 answers reached"), llm.SignInRequired("expired"),
                                 llm.Cancelled()])
def test_rules_signin_and_stop_are_never_bypassed(offline, exc):
    called = []
    with pytest.raises(type(exc)):
        list(llm._with_offline_fallback(_failing(exc), lambda: called.append(1) or iter(["x"])))
    assert not called


def test_no_fallback_after_text_has_started(offline):
    called = []
    with pytest.raises(llm.LLMUnavailable):
        list(llm._with_offline_fallback(_failing(llm.LLMUnavailable("cut"), ["- part "]), lambda: called.append(1) or iter(["x"])))
    assert not called, "never mix half an online answer with an offline one"


def test_user_can_switch_the_fallback_off(monkeypatch):
    monkeypatch.setattr(llm, "_health_ollama", lambda: (True, "Ollama"))
    monkeypatch.setattr(prefs, "get", lambda key, default=None: False if key == "offline_fallback" else default)
    with pytest.raises(llm.LLMUnavailable):
        list(llm._with_offline_fallback(_failing(llm.LLMUnavailable("down")), lambda: iter(["x"])))


def test_stream_messages_uses_the_chain_end_to_end(offline, monkeypatch):
    monkeypatch.setattr(llm.CONFIG, "provider", "openrouter")
    monkeypatch.setattr(llm, "_stream_openrouter_messages", lambda m: _failing(llm.LLMUnavailable("down")))
    monkeypatch.setattr(llm, "_stream_ollama_messages", lambda m: iter(["- from the local model"]))
    assert "".join(llm.stream_messages([{"role": "user", "content": "hi"}])) == "- from the local model"
    assert "offline" in llm.take_note()
