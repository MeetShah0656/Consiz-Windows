"""Central configuration. Everything tunable lives here, nothing is hardcoded elsewhere."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# API keys live in <project>/.env (never committed). Loaded once here; nothing else reads files for secrets.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass
class Config:
    # --- LLM ---
    provider: str = "openrouter"        # "openrouter" (default, cloud, free model) or "ollama" (local)
    openrouter_model: str = os.environ.get("OPENROUTER_MODEL", "inclusionai/ling-3.0-flash-fin:free")   # set in .env — same model as macOS
    openrouter_fallbacks: tuple = ("inclusionai/ling-3.0-flash-sante:free", "nvidia/nemotron-3-ultra-550b-a55b:free")   # OpenRouter allows max 3 models total
    ollama_model: str = "gemma4:e4b"    # only used with --provider ollama
    ollama_host: str = "http://localhost:11434"
    llm_timeout_s: float = 45.0         # hard cap per LLM call
    max_output_tokens: int = 2500       # per request; cost is per token USED, so a high cap is free insurance
    temperature: float = 0.2
    max_input_chars: int = 24_000       # ~6k tokens; longer selections are truncated with a notice

    # --- Trigger ---
    use_middle_click: bool = True
    hotkey: str = "<ctrl>+<alt>+s"      # keyboard fallback, per spec §4 "Fallback"

    # --- Capture ---
    clipboard_settle_s: float = 0.25    # wait after simulated Cmd+C before reading the clipboard

    # --- Classification ---
    confidence_threshold: float = 0.75  # spec §5.2 default
    question_max_chars: int = 300

    # --- Security ---
    redact_sensitive: bool = True       # redact credential-like patterns before the LLM sees them

    # --- Deterministic ---
    folder_max_entries: int = 2000
    file_preview_chars: int = 3000     # ~ first 1–4 paragraphs

    # --- Profile (personal assistant knowledge) ---
    profile_path: str = str(Path(__file__).resolve().parent.parent / "profile.md")

    # --- Dictation & Voice (faster-whisper) ---
    dictate_hotkey: str = os.environ.get("CONSIZ_DICTATE_HOTKEY", "<ctrl>+<alt>+d")
    whisper_model: str = os.environ.get("WHISPER_MODEL", "small")
    whisper_device: str = os.environ.get("WHISPER_DEVICE", "cpu")
    whisper_compute_type: str = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
    whisper_language: Optional[str] = os.environ.get("WHISPER_LANGUAGE", None)
    whisper_detection_segments: int = int(os.environ.get("WHISPER_DETECTION_SEGMENTS", "3"))
    dictate_sample_rate: int = 16000
    dictate_silence_threshold: float = 0.015
    dictate_silence_duration_s: float = 1.2
    dictate_auto_stop_on_silence: bool = os.environ.get("CONSIZ_DICTATE_AUTO_STOP", "").lower() in ("1", "true", "yes")
    dictate_max_duration_s: float = float(os.environ.get("CONSIZ_DICTATE_MAX_DURATION", "120.0"))

    # --- Output ---
    stream: bool = True
    color: bool = True


CONFIG = Config()
