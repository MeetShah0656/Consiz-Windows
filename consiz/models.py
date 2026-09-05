"""Data contracts shared by every stage (mirrors spec §5.1, §5.2, §5.5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Iterator, Optional


class CaptureMethod(str, Enum):
    TEXT_SELECTION = "TEXT_SELECTION"       # accessibility API
    CLIPBOARD_FALLBACK = "CLIPBOARD_FALLBACK"
    FILE_PATH = "FILE_PATH"                 # Finder selection
    FOLDER_PATH = "FOLDER_PATH"
    NONE = "NONE"


class ContentType(str, Enum):
    TEXT_SELECTION = "TEXT_SELECTION"
    QUESTION = "QUESTION"
    FILE = "FILE"
    FOLDER = "FOLDER"
    CSV_DATA = "CSV_DATA"
    UNSUPPORTED = "UNSUPPORTED"


class ErrorState(str, Enum):
    NO_CONTEXT_FOUND = "NO_CONTEXT_FOUND"
    AMBIGUOUS_SELECTION = "AMBIGUOUS_SELECTION"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    DATA_MALFORMED = "DATA_MALFORMED"
    PROCESSING_TIMEOUT = "PROCESSING_TIMEOUT"
    SENSITIVE_CONTENT_BLOCKED = "SENSITIVE_CONTENT_BLOCKED"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"


@dataclass
class CapturedContext:
    source_app: str
    capture_method: CaptureMethod
    raw_content: str                 # selected text, or a path for FILE/FOLDER
    paths: list[str] = field(default_factory=list)   # all selected paths (Finder multi-select)
    note: str = ""                                    # capture-layer hint shown with NO_CONTEXT_FOUND
    timestamp: datetime = field(default_factory=datetime.now)
    source_title: str = ""                            # e.g., page title or window title
    source_url: str = ""                              # e.g., webpage URL
    source_domain: str = ""                           # e.g., website domain (wikipedia.org)
    source_meta: dict[str, Any] = field(default_factory=dict)  # additional site/folder context

    @property
    def size_bytes(self) -> int:
        return len(self.raw_content.encode("utf-8", "ignore"))

    @property
    def is_empty(self) -> bool:
        return not self.raw_content.strip() and not self.paths


@dataclass
class ClassificationResult:
    content_type: ContentType
    confidence: float
    sub_type: str = ""
    reason: str = ""


@dataclass
class NumericalResult:
    computed_stats: dict[str, Any]
    row_count: int
    columns_analyzed: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class Result:
    """What the output layer renders. Phase 2 will render this in a popup instead of the terminal."""
    title: str
    content_type: str
    source_app: str = ""
    body: str = ""                                  # static body (deterministic results / errors)
    stream: Optional[Iterator[str]] = None          # streamed LLM tokens, if any
    warnings: list[str] = field(default_factory=list)
    error: Optional[ErrorState] = None
    started_at: float = 0.0
    source_content: str = ""          # what was selected/derived — context for follow-up questions


def error_result(state: ErrorState, message: str, source_app: str = "") -> Result:
    return Result(title=state.value, content_type="ERROR", source_app=source_app, body=message, error=state)
