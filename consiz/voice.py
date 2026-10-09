"""Voice dictation: is it available, is the speech model on this PC, and the one-time download (shared, no UI).

Privacy: speech is turned into text ON THIS PC (faster-whisper). The audio is never uploaded; only the words you spoke,
exactly like a typed question, go to the AI.

The speech model (a few hundred MB) is not shipped inside the app. The first time the user dictates, they are asked
once, told the size, and it is downloaded with progress; after that it works offline and starts instantly.
"""
from __future__ import annotations

import importlib.util
import os
import threading
from typing import Callable, Optional

from . import prefs
from .i18n import t, tf
from .config import CONFIG

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")      # Windows without developer mode: harmless, just noisy

# name -> (what it is, approximate download size in MB)
MODELS: dict[str, tuple[str, int]] = {
    "small": ("Small: best accuracy, all languages", 484),
    "base": ("Base: faster, a bit less accurate", 145),
    "tiny": ("Tiny: smallest, least accurate", 75),
}


class VoiceError(Exception):
    """A voice problem with a message a person can act on."""


class DownloadCancelled(VoiceError):
    pass


def available() -> bool:
    """The speech parts are part of this build (the packaged exe or a Python with the two packages)."""
    return all(importlib.util.find_spec(m) is not None for m in ("sounddevice", "faster_whisper"))


def enabled() -> bool:
    """Available AND not switched off in Settings."""
    return bool(prefs.get("voice_enabled", True)) and available()


def model_name() -> str:
    return CONFIG.whisper_model


def model_mb(name: Optional[str] = None) -> int:
    return MODELS.get(name or model_name(), ("", 480))[1]


def model_cached(name: Optional[str] = None) -> bool:
    """True when the speech model is already on this PC (then dictation works offline and starts at once)."""
    try:
        from faster_whisper.utils import download_model
        download_model(name or model_name(), local_files_only=True)
        return True
    except Exception:
        return False


def download_model(name: Optional[str] = None, on_progress: Optional[Callable[[int, int], None]] = None,
                   cancel: Optional[threading.Event] = None) -> None:
    """Download the speech model from Hugging Face (the project that publishes it). on_progress(done_bytes, total_bytes)
    is called as it arrives; setting `cancel` stops it (what was already downloaded is kept for next time)."""
    name = name or model_name()
    try:
        from faster_whisper.utils import _MODELS
        repo = _MODELS.get(name) or f"Systran/faster-whisper-{name}"
    except Exception:
        repo = f"Systran/faster-whisper-{name}"
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import tqdm as hf_tqdm

    class Bar(hf_tqdm):
        """Hugging Face draws one progress bar per file. We count the bytes ourselves (so progress and cancel work even
        when its bars are switched off by an environment setting) and only report the big model file."""

        def __init__(self, *args, **kwargs):
            self._unit = kwargs.get("unit", "")
            self._expected = kwargs.get("total") or 0
            self._received = kwargs.get("initial", 0) or 0
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled("cancelled")
            self._received += n or 0
            result = super().update(n)
            if on_progress and self._unit == "B" and self._expected > 5_000_000:
                try:
                    on_progress(int(self._received), int(self._expected))
                except Exception:
                    pass
            return result

    try:
        snapshot_download(repo, allow_patterns=["config.json", "preprocessor_config.json", "model.bin",
                                                "tokenizer.json", "vocabulary.*"], tqdm_class=Bar)
    except DownloadCancelled:
        raise
    except Exception as e:
        raise VoiceError(tf("Could not download the voice model. Check your internet connection and try again. ({error})",
                            error=type(e).__name__)) from e


def prepare(consent: Callable[[str, int], bool], progress: Callable[[str], None],
            cancel: Optional[threading.Event] = None) -> tuple[bool, str]:
    """Make voice ready to start RIGHT NOW. Returns (ok, why_not). Runs on a worker thread (it may wait for the user or
    the network).
      - not part of this build / switched off  -> (False, reason)
      - model already here                     -> warm it up while the user speaks; (True, "")
      - model missing                          -> ask ONCE with the size; No -> (False, ""); Yes -> download with progress
    """
    if not available():
        return False, t("Voice dictation is not included in this version of Consiz.")
    if not prefs.get("voice_enabled", True):
        return False, t("Voice dictation is switched off in Settings.")
    from .dictation import get_dictation_engine
    if model_cached():
        get_dictation_engine().warmup()                     # load the model while the person is still speaking
        return True, ""
    name = model_name()
    if not consent(name, model_mb(name)):
        return False, ""
    try:
        progress(tf("Downloading the voice model (about {mb} MB, one time)…", mb=model_mb(name)))
        last = [-1]

        def on_progress(done: int, total: int) -> None:
            pct = int(100 * done / max(total, 1))
            if pct != last[0] and pct % 2 == 0:
                last[0] = pct
                progress(tf("Downloading the voice model… {pct}%  ({done} of {total} MB)", pct=pct,
                            done=done // 1_048_576, total=total // 1_048_576))

        download_model(name, on_progress, cancel)
    except DownloadCancelled:
        return False, t("Voice model download cancelled. It will ask again next time.")
    except VoiceError as e:
        return False, str(e)
    get_dictation_engine().warmup()
    return True, ""
