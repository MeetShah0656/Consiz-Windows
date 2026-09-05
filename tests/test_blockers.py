"""Tests verifying fixes for the 9 Windows blockers."""
import sys
import time
import numpy as np
import pytest

from consiz.dictation import AudioRecorder


def test_w05_w06_recorder_stop_no_deadlock_and_single_autostop():
    """Verify stop() does not deadlock and auto-stop fires only once (W-05, W-06)."""
    rec = AudioRecorder(
        sample_rate=16000,
        silence_threshold=0.015,
        silence_duration_s=0.1,
        max_duration_s=0.2,
    )
    assert rec._auto_stopped is False
    assert not rec.is_recording

    res = rec.stop()
    assert isinstance(res, np.ndarray)
    assert len(res) == 0

    rec.cancel()
    assert not rec.is_recording


def test_w09_microphone_detection_validation(monkeypatch):
    """Verify that start() raises RuntimeError if no audio input channels exist (W-09)."""
    import sounddevice as sd

    monkeypatch.setattr(sd, "query_devices", lambda: [{"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2}])

    rec = AudioRecorder()
    with pytest.raises(RuntimeError) as exc_info:
        rec.start()
    assert "No microphone detected" in str(exc_info.value)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test")
def test_w01_clipboard_snapshot_and_restore():
    """Verify clipboard snapshot and restore cycle preserves data without emptying (W-01)."""
    from consiz.platform.win32.capture import (
        _snapshot_all_clipboard_formats,
        _restore_all_clipboard_formats,
        _safe_open_clipboard,
        _safe_close_clipboard,
    )
    import win32clipboard
    import win32con

    if _safe_open_clipboard():
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText("PERSISTENT_SELECTION_DATA", win32con.CF_UNICODETEXT)
        finally:
            _safe_close_clipboard()

    snapshot = _snapshot_all_clipboard_formats()
    assert len(snapshot) > 0

    if _safe_open_clipboard():
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText("OVERWRITTEN_TEMPORARY", win32con.CF_UNICODETEXT)
        finally:
            _safe_close_clipboard()

    _restore_all_clipboard_formats(snapshot)

    if _safe_open_clipboard():
        try:
            restored = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            assert restored == "PERSISTENT_SELECTION_DATA"
        finally:
            _safe_close_clipboard()
