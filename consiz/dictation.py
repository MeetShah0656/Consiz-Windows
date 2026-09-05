"""Dictation and Speech-to-Text Module for Consiz using faster-whisper and sounddevice.

Enables audio capture from the microphone and lightning-fast local transcription
directly from in-memory numpy buffers (no disk I/O).
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time
from typing import Callable, Optional

import numpy as np

from .config import CONFIG

logger = logging.getLogger(__name__)

LANGUAGES: dict[str, str] = {
    "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German",
    "ja": "Japanese", "zh": "Chinese", "gu": "Gujarati", "mr": "Marathi", "ta": "Tamil",
    "te": "Telugu", "bn": "Bengali", "pa": "Punjabi", "ur": "Urdu", "ar": "Arabic",
    "ru": "Russian", "pt": "Portuguese", "it": "Italian", "nl": "Dutch", "ko": "Korean",
    "tr": "Turkish", "pl": "Polish", "uk": "Ukrainian", "vi": "Vietnamese", "id": "Indonesian",
    "th": "Thai", "sv": "Swedish", "el": "Greek", "cs": "Czech", "ro": "Romanian",
    "da": "Danish", "fi": "Finnish", "he": "Hebrew", "fa": "Persian", "hu": "Hungarian",
    "no": "Norwegian", "sk": "Slovak", "ms": "Malay", "kn": "Kannada", "ml": "Malayalam",
}



def detect_script(text: str) -> Optional[tuple[str, str]]:
    """Detect dominant non-Latin script from Unicode character ranges.
    Returns (lang_code, lang_name) or None.
    """
    if not text:
        return None
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        if 0x0A80 <= cp <= 0x0AFF:
            counts["gu"] = counts.get("gu", 0) + 1  # Gujarati
        elif 0x0900 <= cp <= 0x097F:
            counts["hi"] = counts.get("hi", 0) + 1  # Devanagari (Hindi / Marathi)
        elif 0x0980 <= cp <= 0x09FF:
            counts["bn"] = counts.get("bn", 0) + 1  # Bengali
        elif 0x0A00 <= cp <= 0x0A7F:
            counts["pa"] = counts.get("pa", 0) + 1  # Gurmukhi / Punjabi
        elif 0x0B80 <= cp <= 0x0BFF:
            counts["ta"] = counts.get("ta", 0) + 1  # Tamil
        elif 0x0C00 <= cp <= 0x0C7F:
            counts["te"] = counts.get("te", 0) + 1  # Telugu
        elif 0x0C80 <= cp <= 0x0CFF:
            counts["kn"] = counts.get("kn", 0) + 1  # Kannada
        elif 0x0D00 <= cp <= 0x0D7F:
            counts["ml"] = counts.get("ml", 0) + 1  # Malayalam
        elif 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F:
            counts["ar"] = counts.get("ar", 0) + 1  # Arabic / Urdu / Persian
        elif 0x0400 <= cp <= 0x04FF:
            counts["ru"] = counts.get("ru", 0) + 1  # Cyrillic (Russian / Ukrainian)
        elif 0x4E00 <= cp <= 0x9FFF:
            counts["zh"] = counts.get("zh", 0) + 1  # Chinese
        elif 0x3040 <= cp <= 0x30FF:
            counts["ja"] = counts.get("ja", 0) + 1  # Japanese
        elif 0xAC00 <= cp <= 0xD7AF:
            counts["ko"] = counts.get("ko", 0) + 1  # Korean
        elif 0x0370 <= cp <= 0x03FF:
            counts["el"] = counts.get("el", 0) + 1  # Greek
        elif 0x0590 <= cp <= 0x05FF:
            counts["he"] = counts.get("he", 0) + 1  # Hebrew
        elif 0x0E00 <= cp <= 0x0E7F:
            counts["th"] = counts.get("th", 0) + 1  # Thai

    if not counts:
        return None
    top_code, count = max(counts.items(), key=lambda x: x[1])
    if count >= 2:
        return top_code, LANGUAGES.get(top_code, top_code.upper())
    return None


@dataclass
class TranscriptionResult:
    """Transcription output including detected language metadata."""
    text: str
    language: str = "en"
    language_name: str = "English"
    language_probability: float = 1.0

    def __str__(self) -> str:
        return self.text

    def __bool__(self) -> bool:
        return bool(self.text.strip())


_ENGINE: Optional["DictationEngine"] = None
_ENGINE_LOCK = threading.Lock()


class AudioRecorder:
    """Non-blocking microphone recorder capturing 16kHz float32 audio."""

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_threshold: float = 0.015,
        silence_duration_s: float = 1.2,
        max_duration_s: float = 120.0,
        auto_stop_on_silence: Optional[bool] = None,
    ):
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.silence_duration_s = silence_duration_s
        self.max_duration_s = max_duration_s
        self.auto_stop_on_silence = (
            auto_stop_on_silence
            if auto_stop_on_silence is not None
            else getattr(CONFIG, "dictate_auto_stop_on_silence", False)
        )

        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._recording = False
        self._speech_started = False
        self._last_speech_time = 0.0
        self._start_time = 0.0
        self._on_level: Optional[Callable[[float], None]] = None
        self._on_auto_stop: Optional[Callable[[], None]] = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(
        self,
        on_level: Optional[Callable[[float], None]] = None,
        on_auto_stop: Optional[Callable[[], None]] = None,
    ) -> None:
        """Start capturing microphone audio."""
        import sounddevice as sd

        with self._lock:
            if self._recording:
                return
            self._chunks.clear()
            self._recording = True
            self._speech_started = False
            self._start_time = time.time()
            self._last_speech_time = self._start_time
            self._on_level = on_level
            self._on_auto_stop = on_auto_stop

        def audio_callback(indata, frames, time_info, status):
            if not self._recording:
                return
            chunk = indata.copy().flatten()
            with self._lock:
                self._chunks.append(chunk)

            # Calculate RMS audio energy
            rms = float(np.sqrt(np.mean(chunk**2))) if len(chunk) > 0 else 0.0

            if self._on_level:
                try:
                    self._on_level(rms)
                except Exception:
                    pass

            now = time.time()
            # Speech activity detection
            if rms >= self.silence_threshold:
                self._speech_started = True
                self._last_speech_time = now
            elif self._speech_started and self.auto_stop_on_silence:
                # Only auto-stop on silence if explicitly enabled (keeps listening until 'Done' by default)
                if (now - self._last_speech_time) >= self.silence_duration_s:
                    self._trigger_auto_stop()
                    return

            # Max duration safeguard (safety timeout)
            if (now - self._start_time) >= self.max_duration_s:
                self._trigger_auto_stop()

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=audio_callback,
        )
        self._stream.start()

    def _trigger_auto_stop(self) -> None:
        auto_stop_cb = self._on_auto_stop
        threading.Thread(target=self._run_auto_stop, args=(auto_stop_cb,), daemon=True).start()

    def _run_auto_stop(self, cb: Optional[Callable[[], None]]) -> None:
        if cb:
            try:
                cb()
            except Exception:
                pass

    def stop(self) -> np.ndarray:
        """Stop recording and return captured audio as 1D float32 numpy array."""
        with self._lock:
            self._recording = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            if not self._chunks:
                return np.zeros(0, dtype=np.float32)

            audio = np.concatenate(self._chunks, axis=0).astype(np.float32)
            self._chunks.clear()
            return audio

    def cancel(self) -> None:
        """Cancel and discard recording."""
        with self._lock:
            self._recording = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._chunks.clear()


class DictationEngine:
    """Manages faster-whisper WhisperModel lifecycle and transcription."""

    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ):
        self.model_size = model_size or CONFIG.whisper_model
        self.device = device or CONFIG.whisper_device
        self.compute_type = compute_type or CONFIG.whisper_compute_type
        self._model = None
        self._init_lock = threading.Lock()

    def _load_model(self):
        if self._model is None:
            with self._init_lock:
                if self._model is None:
                    from faster_whisper import WhisperModel

                    try:
                        self._model = WhisperModel(
                            self.model_size,
                            device=self.device,
                            compute_type=self.compute_type,
                        )
                    except Exception as e:
                        # Fallback to cpu int8, then base if cuda or specific model fails
                        logger.warning(f"Failed to load {self.model_size} on {self.device}: {e}. Retrying on cpu/int8.")
                        try:
                            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
                        except Exception as e2:
                            logger.warning(f"Failed to load {self.model_size} on cpu/int8: {e2}. Falling back to base model.")
                            self._model = WhisperModel("base", device="cpu", compute_type="int8")
        return self._model

    def warmup(self) -> None:
        """Pre-load model in background to eliminate first-use latency."""
        def _warm():
            try:
                self._load_model()
            except Exception as e:
                logger.error(f"Error warming up WhisperModel: {e}")

        threading.Thread(target=_warm, name="whisper-warmup", daemon=True).start()

    def transcribe(self, audio: np.ndarray, language: Optional[str] = None) -> TranscriptionResult:
        """Transcribe in-memory 16kHz float32 audio array and detect spoken language accurately."""
        if audio is None or len(audio) == 0:
            return TranscriptionResult(text="", language="en", language_name="English", language_probability=0.0)

        # Normalize audio if needed
        max_abs = np.max(np.abs(audio)) if len(audio) > 0 else 0.0
        if max_abs > 1.0:
            audio = audio / max_abs

        # Minimum required audio length ~0.25s to avoid meaningless hallucination
        if len(audio) < int(CONFIG.dictate_sample_rate * 0.25):
            return TranscriptionResult(text="", language="en", language_name="English", language_probability=0.0)

        model = self._load_model()
        target_lang = language or getattr(CONFIG, "whisper_language", None)
        detected_prob = 1.0
        detection_segments = getattr(CONFIG, "whisper_detection_segments", 3)

        # Two-phase accurate language identification:
        # If language is not manually specified, run multi-segment detection first with VAD
        if not target_lang:
            try:
                det_lang, det_prob, _ = model.detect_language(
                    audio,
                    vad_filter=True,
                    language_detection_segments=detection_segments,
                )
                logger.info(f"Whisper multi-segment language detection: {det_lang} ({det_prob:.1%})")
                target_lang = det_lang
                detected_prob = float(det_prob)
            except Exception as e:
                logger.warning(f"Whisper detect_language failed ({e}); proceeding with transcription auto-detection")
                target_lang = None

        # Transcribe directly from numpy array (zero disk I/O)
        kwargs = {
            "beam_size": 5,
            "vad_filter": True,
            "condition_on_previous_text": False,  # Prevents hallucination repetition loops
            "language_detection_segments": detection_segments,
        }
        if target_lang:
            kwargs["language"] = target_lang

        segments, info = model.transcribe(audio, **kwargs)
        pieces = [seg.text.strip() for seg in segments if seg.text.strip()]
        result = " ".join(pieces).strip()

        # Extract detected language
        final_lang = target_lang or getattr(info, "language", "en") or "en"
        if hasattr(info, "language_probability") and info.language_probability:
            detected_prob = float(info.language_probability)

        # Post-transcription Script Verification:
        # If transcribed text contains non-Latin scripts (e.g. Gujarati, Devanagari, Arabic),
        # verify and prioritize that script over acoustic approximations.
        script_match = detect_script(result)
        if script_match:
            script_code, script_name = script_match
            if final_lang != script_code:
                logger.info(f"Script verification adjusted language from {final_lang} to {script_code} ({script_name})")
            final_lang = script_code
            lang_name = script_name
            detected_prob = max(detected_prob, 0.99)
        else:
            lang_name = LANGUAGES.get(final_lang, final_lang.upper())

        return TranscriptionResult(
            text=result,
            language=final_lang,
            language_name=lang_name,
            language_probability=detected_prob,
        )


def get_dictation_engine() -> DictationEngine:
    """Get or create singleton DictationEngine."""
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = DictationEngine()
    return _ENGINE
