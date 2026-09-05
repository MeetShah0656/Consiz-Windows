"""Result Interface (spec §5.6) — Phase 1: terminal. Phase 2 swaps this module for a popup next to the selection."""
from __future__ import annotations

import sys
import time

from .config import CONFIG
from .llm import KIND_TITLES, LLMError
from .models import Result

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass



def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if CONFIG.color else s


BOLD, DIM, CYAN, GREEN, YELLOW, RED = "1", "2", "36", "32", "33", "31"


def notify(msg: str) -> None:
    print(_c(DIM, f"▶ {msg}"), flush=True)


def _pretty_line(line: str) -> str:
    """'- item' → '• item', '  - sub' → '    ◦ sub'. Strips stray markdown bold."""
    line = line.rstrip().replace("**", "")
    stripped = line.lstrip()
    indent = len(line) - len(stripped)
    if stripped.startswith(("- ", "* ", "• ")):
        return ("    ◦ " if indent else "• ") + stripped[2:]
    return line


def render(res: Result) -> None:
    w = 72
    print()
    if res.error:
        print(_c(RED, f"✖ {res.title}") + _c(DIM, f"  · {res.source_app}"))
        print("  " + res.body)
        print(_c(DIM, "─" * w))
        return

    def header(title: str) -> None:
        print(_c(BOLD + ";" + CYAN, f"● {title}") + _c(DIM, f"  · {res.content_type} · {res.source_app}"))

    collected = []
    if res.title != "auto":
        header(res.title)
    if res.body:
        for line in res.body.splitlines():
            print("  " + line)
    if res.stream is not None:
        if res.body:
            print()
        try:
            it = iter(res.stream)
            title_done = res.title != "auto"
            line = ""                       # current, not-yet-finished line
            collected_lines: list[str] = []

            def flush(text_line: str) -> None:
                sys.stdout.write("  " + _pretty_line(text_line) + "\n")
                sys.stdout.flush()

            for piece in it:
                collected.append(piece)
                line += piece
                while "\n" in line:
                    done, line = line.split("\n", 1)
                    if not done.strip() and (not title_done or not collected_lines):
                        continue            # skip blank lines before/just after the KIND line
                    if not title_done:      # first line is `KIND: X`
                        title_done = True
                        k = done.strip().strip("*`#_ ").upper()
                        if k.startswith("KIND"):
                            header(KIND_TITLES.get(k.removeprefix("KIND").strip(":*` _"), "Result"))
                            continue
                        header("Result")
                    collected_lines.append(done)
                    flush(done)
            if not title_done:
                header("Result")
            if line.strip():
                flush(line)
        except LLMError as e:
            if res.title == "auto":
                header("Result")
            print()
            print(_c(RED, f"✖ BACKEND_UNAVAILABLE") + f"  {e}")
    text = "".join(collected)
    if text.upper().startswith("KIND"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    extra = res.on_complete(text) if getattr(res, "on_complete", None) and text else []
    for wmsg in res.warnings + extra:
        print(_c(YELLOW, f"  ⚠ {wmsg}"))
    latency = time.perf_counter() - res.started_at if res.started_at else 0
    print(_c(DIM, f"─" * w + f" {latency:.1f}s"))
