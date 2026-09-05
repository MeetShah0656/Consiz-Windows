"""Tests for dictation module, language identification, and voice command processing."""
import numpy as np
import pytest

from consiz.config import CONFIG
from consiz.dictation import AudioRecorder, DictationEngine, TranscriptionResult, LANGUAGES, detect_script
from consiz import llm
from consiz.models import CapturedContext, CaptureMethod
from consiz.router import process_dictation


def test_audio_recorder_init():
    rec = AudioRecorder(sample_rate=16000, silence_threshold=0.02, silence_duration_s=1.0)
    assert rec.sample_rate == 16000
    assert rec.silence_threshold == 0.02
    assert rec.silence_duration_s == 1.0
    assert not rec.is_recording
    assert rec.auto_stop_on_silence is False


def test_detect_script_multilingual():
    # Gujarati script detection
    gu_match = detect_script("આ લખાણનો સારાંશ આપો")
    assert gu_match is not None
    assert gu_match[0] == "gu"
    assert gu_match[1] == "Gujarati"

    # Devanagari / Hindi script detection
    hi_match = detect_script("इस कोड को विस्तार से समझाइए")
    assert hi_match is not None
    assert hi_match[0] == "hi"
    assert hi_match[1] == "Hindi"

    # Arabic script detection
    ar_match = detect_script("لخص هذا النص باللغة العربية")
    assert ar_match is not None
    assert ar_match[0] == "ar"
    assert ar_match[1] == "Arabic"

    # Russian Cyrillic script detection
    ru_match = detect_script("Переведи этот фрагмент")
    assert ru_match is not None
    assert ru_match[0] == "ru"
    assert ru_match[1] == "Russian"

    # Japanese script detection
    ja_match = detect_script("これを日本語で説明してください")
    assert ja_match is not None
    assert ja_match[0] == "ja"
    assert ja_match[1] == "Japanese"

    # Pure English / Latin returns None (uses acoustic Whisper detection)
    en_match = detect_script("Translate this into Gujarati and give it to me")
    assert en_match is None


def test_audio_recorder_continuous_listening():
    import time
    stopped = False

    def on_stop():
        nonlocal stopped
        stopped = True

    rec = AudioRecorder(
        sample_rate=16000,
        silence_threshold=0.01,
        silence_duration_s=0.1,
        max_duration_s=5.0,
        auto_stop_on_silence=False,
    )
    assert rec.auto_stop_on_silence is False


def test_transcription_result_properties():
    res = TranscriptionResult(text="Hola mundo", language="es", language_name="Spanish", language_probability=0.98)
    assert res.text == "Hola mundo"
    assert res.language == "es"
    assert res.language_name == "Spanish"
    assert str(res) == "Hola mundo"
    assert bool(res) is True

    empty = TranscriptionResult(text="")
    assert bool(empty) is False


def test_dictation_messages_multilingual():
    content = "def add(a, b): return a + b"
    instruction = "Explica esta función en detalle"
    msgs = llm.dictate_messages(content, instruction, language_name="Spanish")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "<content>" in msgs[1]["content"]
    assert content in msgs[1]["content"]
    assert instruction in msgs[1]["content"]
    assert "spoken in Spanish" in msgs[1]["content"]


def test_process_dictation_empty_instruction():
    ctx = CapturedContext("test", CaptureMethod.TEXT_SELECTION, "some text")
    res = process_dictation(ctx, "")
    assert res.error
    assert "No voice instruction was detected" in res.body


def test_process_dictation_empty_content():
    ctx = CapturedContext("test", CaptureMethod.TEXT_SELECTION, "")
    res = process_dictation(ctx, "summarize")
    assert res.error
    assert "No text was selected" in res.body


def test_process_dictation_copy_action_multilingual():
    text = "Important text to copy"
    ctx = CapturedContext("test", CaptureMethod.TEXT_SELECTION, text)

    # Spanish copy command
    t_res_es = TranscriptionResult(text="copiar", language="es", language_name="Spanish")
    res = process_dictation(ctx, t_res_es)
    assert res.content_type == "ACTION"
    assert "Copied selected text" in res.body

    # Hindi copy command
    t_res_hi = TranscriptionResult(text="कॉपी करो", language="hi", language_name="Hindi")
    res_hi = process_dictation(ctx, t_res_hi)
    assert res_hi.content_type == "ACTION"
    assert "Copied selected text" in res_hi.body


def test_process_dictation_multilingual_badge():
    text = "Machine learning is a subset of artificial intelligence."
    ctx = CapturedContext("test", CaptureMethod.TEXT_SELECTION, text)
    t_res = TranscriptionResult(text="Resumir en 2 puntos", language="es", language_name="Spanish", language_probability=0.97)

    res = process_dictation(ctx, t_res)
    assert not res.error
    assert "[Spanish]" in res.title
    assert "Resumir en 2 puntos" in res.title
    assert "VOICE (Spanish)" in res.content_type
    assert res.stream is not None


def test_whisper_transcribe_silence():
    # Test faster-whisper with tiny.en model on synthetic silent audio array
    engine = DictationEngine(model_size="tiny.en", device="cpu", compute_type="int8")
    # 0.5 seconds of 16kHz silence
    silence = np.zeros(8000, dtype=np.float32)
    res = engine.transcribe(silence)
    assert isinstance(res, TranscriptionResult)
    assert res.language == "en"
