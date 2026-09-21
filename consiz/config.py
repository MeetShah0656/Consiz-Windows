"""Central configuration. Everything tunable lives here, nothing is hardcoded elsewhere."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# API keys live in <project>/.env (never committed). Loaded once here; nothing else reads files for secrets.
PROJECT_ENV = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(PROJECT_ENV)


def ensure_env_template() -> tuple[Path, bool]:
    """Create <project>/.env from .env.example if it doesn't exist yet. Returns (path, just_created)."""
    if PROJECT_ENV.exists():
        return PROJECT_ENV, False
    example = Path(__file__).resolve().parent.parent / ".env.example"
    try:
        template = example.read_text(encoding="utf-8")
    except OSError:
        template = "OPENROUTER_API_KEY=sk-or-v1-paste-your-key-here\n"
    PROJECT_ENV.write_text(
        "# Consiz settings — paste your OpenRouter key below, then save this file and restart Consiz.\n"
        "# Get a free key at: https://openrouter.ai/keys\n\n" + template,
        encoding="utf-8",
    )
    return PROJECT_ENV, True


def set_openrouter_key(key: str) -> None:
    """Write (or replace) OPENROUTER_API_KEY in .env and reload it live — no restart needed, since the
    key is also written directly into os.environ so _api_key() in llm.py picks it up immediately."""
    import re
    ensure_env_template()
    text = PROJECT_ENV.read_text(encoding="utf-8")
    line = f"OPENROUTER_API_KEY={key}"
    if re.search(r"(?m)^OPENROUTER_API_KEY=", text):
        text = re.sub(r"(?m)^OPENROUTER_API_KEY=.*$", line, text)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    PROJECT_ENV.write_text(text, encoding="utf-8")
    os.environ["OPENROUTER_API_KEY"] = key   # live update — no restart needed
    load_dotenv(PROJECT_ENV, override=True)


_PROFILE_TEMPLATE = """# My Profile — Consiz uses this to answer AS YOUR ASSISTANT
# Edit freely. Delete anything you don't want the AI to know.
# It is used ONLY when relevant (drafting replies, quotes, advice for you) —
# never for neutral tasks like summarizing an article.

## Who I am
Name:
Profession: (e.g. CA student / CA / accountant / business owner / student)
City:

## Why I use Consiz


## My work / business
What I do:
Company name:
What we sell / services:

## My pricing (used when drafting quotes — leave empty and Consiz will refuse to invent prices)
Example: Logo design — ₹5,000 · Website — ₹40,000 · Consulting — ₹2,000/hour

## How I like replies written
Tone: (e.g. polite, short, professional, Hinglish ok)
Sign-off: (e.g. Regards, Hitarth)
"""


def save_profile_basics(name: str, profession: str, reason: str) -> None:
    """Write the onboarding wizard's three answers into the profile's existing fields (never invents new
    ones — 'Name:', 'Profession:' and '## Why I use Consiz' already exist in the template above, so this
    is filling in blanks the file already expects, not a new format)."""
    import re
    path = Path(CONFIG.profile_path)
    if not path.exists():
        path.write_text(_PROFILE_TEMPLATE, encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    if name.strip():
        text = re.sub(r"(?m)^Name:.*$", f"Name: {name.strip()}", text, count=1)
    if profession.strip():
        text = re.sub(r"(?m)^Profession:.*$", f"Profession: {profession.strip()}", text, count=1)
    if reason.strip():
        heading = re.search(r"(?m)^## Why I use Consiz[ \t]*$", text)
        if heading:
            next_heading = re.search(r"(?m)^## ", text[heading.end():])
            body_end = heading.end() + next_heading.start() if next_heading else len(text)
            text = text[:heading.start()] + f"## Why I use Consiz\n{reason.strip()}\n\n" + text[body_end:]
        else:
            text = text.rstrip("\n") + f"\n\n## Why I use Consiz\n{reason.strip()}\n"
    path.write_text(text, encoding="utf-8")


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
