"""T-02: the windowless exe must leave evidence of errors, and the evidence must never contain user content/secrets."""
import logging
import logging.handlers
import sys
import threading

import pytest

from consiz import logs


@pytest.fixture
def fresh_log(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "LOG_FILE", tmp_path / "consiz.log")
    log = logging.getLogger("consiz")
    for h in list(log.handlers):
        log.removeHandler(h)
    monkeypatch.setitem(logs._state, "ready", False)
    saved = (sys.excepthook, threading.excepthook, sys.unraisablehook)
    yield logs.setup()
    for h in list(log.handlers):
        h.close()
        log.removeHandler(h)
    sys.excepthook, threading.excepthook, sys.unraisablehook = saved


def _read():
    for h in logging.getLogger("consiz").handlers:
        h.flush()
    return logs.LOG_FILE.read_text(encoding="utf-8")


def test_setup_is_idempotent_and_writes_a_file(fresh_log):
    logs.setup()
    logs.setup()
    fresh_log.info("hello from a test")
    files = [h for h in fresh_log.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(files) == 1, "two setup() calls must not add a second file handler (pytest adds its own capture handlers: ignore those)"
    assert "hello from a test" in _read()


def test_secrets_never_reach_the_file(fresh_log):
    fresh_log.info("request failed token=abcdef123456789 and password: hunter22secret and key sk-or-v1-%s", "a" * 40)
    text = _read()
    assert "hunter22secret" not in text and "a" * 40 not in text and "REDACTED" in text


def test_main_thread_crash_leaves_a_traceback(fresh_log):
    try:
        raise ValueError("boom in main")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    text = _read()
    assert "UNHANDLED ValueError" in text and "Traceback" in text and "boom in main" in text


def test_worker_thread_crash_leaves_a_traceback(fresh_log):
    def boom():
        raise RuntimeError("boom in worker")

    t = threading.Thread(target=boom, name="consiz-test-worker")
    t.start()
    t.join()
    text = _read()
    assert "THREAD CRASH in consiz-test-worker" in text and "boom in worker" in text


def test_handled_errors_can_be_logged_from_except_blocks(fresh_log):
    try:
        1 / 0
    except ZeroDivisionError:
        logs.exception("unit test")
    assert "ERROR in unit test" in _read() and "ZeroDivisionError" in _read()


def test_diagnostics_has_versions_and_recent_lines_but_no_secrets(fresh_log):
    fresh_log.info("sample event")
    text = logs.diagnostics()
    assert "Consiz " in text and "Windows" in text and "sample event" in text and "provider=" in text
    assert "@" not in text.split("---- last log lines ----")[0]        # no email address in the header


def test_file_rotates_instead_of_growing_forever(fresh_log, monkeypatch):
    handler = fresh_log.handlers[0]
    assert handler.maxBytes == 512_000 and handler.backupCount == 2
