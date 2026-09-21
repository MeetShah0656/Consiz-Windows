#!/usr/bin/env python3
"""As Conciz — Phase 1 terminal MVP.

Run:   python3 main.py                 # listen for middle-click / hotkey, print results here
       python3 main.py --text "..."    # run the pipeline on given text (no listener)
       python3 main.py --path FILE     # run the pipeline on a file or folder
       python3 main.py --capture       # capture the current selection once and process it
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

from consiz import llm, output
from consiz.config import CONFIG
from consiz.dictation import AudioRecorder, get_dictation_engine
from consiz.models import CapturedContext, CaptureMethod
from consiz.router import process, process_dictation

_MUTEX_HANDLE = None


def acquire_single_instance_lock() -> bool:
    """Ensures only one instance of Consiz runs as a background listener (KI-16)."""
    global _MUTEX_HANDLE
    if sys.platform == "win32":
        import ctypes
        ERROR_ALREADY_EXISTS = 183
        _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ConsizSingleInstanceMutex")
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return False
        return True
    else:
        try:
            import fcntl
            lock_path = "/tmp/consiz.lock"
            _MUTEX_HANDLE = open(lock_path, "w")
            fcntl.flock(_MUTEX_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            return False


def run_once(ctx: CapturedContext) -> None:
    output.notify(f"captured {ctx.size_bytes} bytes from {ctx.source_app} via {ctx.capture_method.value.lower()} — processing…")
    output.render(process(ctx))


def run_terminal_dictation(ctx: CapturedContext) -> None:
    engine = get_dictation_engine()
    rec = AudioRecorder(
        sample_rate=CONFIG.dictate_sample_rate,
        silence_threshold=CONFIG.dictate_silence_threshold,
        silence_duration_s=CONFIG.dictate_silence_duration_s,
        max_duration_s=CONFIG.dictate_max_duration_s,
    )
    output.notify("🎙 Listening... Speak your command for the selected text (press Enter when finished):")

    done_event = threading.Event()

    def on_auto_stop():
        done_event.set()

    try:
        rec.start(on_auto_stop=on_auto_stop)
    except Exception as e:
        output.notify(f"Microphone error: {e}")
        return

    # Wait for Enter key or safety timeout
    def wait_for_enter():
        try:
            input()
        except Exception:
            pass
        done_event.set()

    t = threading.Thread(target=wait_for_enter, daemon=True)
    t.start()
    done_event.wait(timeout=CONFIG.dictate_max_duration_s)

    audio = rec.stop()
    output.notify("⚡ Transcribing with faster-whisper…")
    res = engine.transcribe(audio)
    if not res.text:
        output.notify("No speech detected.")
        return
    output.notify(f"🎙 Dictated ({res.language_name} ~{res.language_probability:.0%}): \"{res.text}\" — processing…")
    result = process_dictation(ctx, res)
    output.render(result)


POPUP = None


def on_trigger(source: str) -> None:
    from consiz.capture import capture
    output.notify(f"trigger: {source}")
    ctx = capture()
    output.notify(f"captured {ctx.size_bytes} bytes from {ctx.source_app} via {ctx.capture_method.value.lower()} — processing…")
    res = process(ctx)
    if POPUP is not None:
        POPUP.show_result(res)
    else:
        output.render(res)


def on_dictate_trigger(source: str) -> None:
    from consiz.capture import capture
    output.notify(f"dictate trigger: {source}")
    if POPUP is not None and getattr(POPUP, "_is_dictating", False):
        output.notify("🎙 Stopping dictation on toggle…")
        POPUP.stop_dictation()
        return
    ctx = capture()
    output.notify(f"captured {ctx.size_bytes} bytes from {ctx.source_app} via {ctx.capture_method.value.lower()} — starting dictation…")
    if POPUP is not None:
        POPUP.start_dictation_flow(ctx)
    else:
        run_terminal_dictation(ctx)


def main() -> int:
    ap = argparse.ArgumentParser(description="As Conciz terminal MVP")
    ap.add_argument("--text", help="process this text instead of listening")
    ap.add_argument("--path", help="process this file/folder instead of listening")
    ap.add_argument("--capture", action="store_true", help="capture current selection once, process, exit")
    ap.add_argument("--dictate", action="store_true", help="start dictation immediately on text or current selection")
    ap.add_argument("--whisper-model", default=None, help="faster-whisper model size (e.g. tiny.en, base.en, small.en)")
    ap.add_argument("--dictate-hotkey", default=CONFIG.dictate_hotkey, help="keyboard shortcut for dictation")
    ap.add_argument("--provider", choices=["openrouter", "ollama"], default=CONFIG.provider)
    ap.add_argument("--model", default=None, help="override model id for the chosen provider")
    ap.add_argument("--no-stream", action="store_true")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--terminal", action="store_true", help="print results in the terminal instead of the popup window")
    ap.add_argument("--hotkey", default=CONFIG.hotkey, help="keyboard fallback, pynput syntax (e.g. '<ctrl>+<alt>+s')")
    ap.add_argument("--elevate", action="store_true", help="re-launch with elevated Administrator privileges on Windows")
    args = ap.parse_args()
    CONFIG.provider, CONFIG.hotkey = args.provider, args.hotkey
    if args.dictate_hotkey:
        CONFIG.dictate_hotkey = args.dictate_hotkey
    if args.whisper_model:
        CONFIG.whisper_model = args.whisper_model
    if args.model:
        if args.provider == "ollama":
            CONFIG.ollama_model = args.model
        else:
            CONFIG.openrouter_model = args.model
    CONFIG.stream, CONFIG.color = not args.no_stream, not args.no_color

    if sys.platform == "win32":
        from consiz.platform.win32.priority import is_admin, request_admin_elevation, set_high_priority
        if args.elevate and not is_admin():
            request_admin_elevation()
        set_high_priority()
        admin_status = "Admin ✓ (Top Priority)" if is_admin() else "Standard User"
        output.notify(f"Windows Integrity: {admin_status}")

    ok, msg = llm.health()
    output.notify(("✓ " if ok else "✗ ") + msg)

    # Pre-warm faster-whisper model in background
    get_dictation_engine().warmup()

    if args.dictate:
        if args.text is not None:
            ctx = CapturedContext("cli", CaptureMethod.TEXT_SELECTION, args.text)
        elif args.capture:
            from consiz.capture import capture
            ctx = capture()
        else:
            from consiz.capture import capture
            ctx = capture()
        run_terminal_dictation(ctx)
        return 0

    if args.text is not None:
        run_once(CapturedContext("cli", CaptureMethod.TEXT_SELECTION, args.text))
        return 0
    if args.path:
        import os
        p = os.path.abspath(os.path.expanduser(args.path))
        m = CaptureMethod.FOLDER_PATH if os.path.isdir(p) else CaptureMethod.FILE_PATH
        run_once(CapturedContext("cli", m, p, paths=[p]))
        return 0
    if args.capture:
        from consiz.capture import capture
        run_once(capture())
        return 0

    if not acquire_single_instance_lock():
        output.notify("Consiz is already running in another window/process. Only one instance can listen for triggers.")
        return 1

    from consiz.trigger import Trigger
    # Dictation hotkey temporarily disabled (not yet part of the shared Mac feature
    # set — see As-Conciz/20-For-Meet-What-Consiz-Does-Today-Plain-Words.md). Backend
    # (on_dictate_trigger, run_terminal_dictation, consiz/dictation.py) is untouched —
    # passing on_dictate=on_dictate_trigger here re-enables it.
    trig = Trigger(
        on_trigger,
        on_busy=lambda: output.notify("still working on the previous request — wait a moment"),
    )
    trig.start()
    where = "in the terminal" if args.terminal else "in a popup next to your selection"
    print(output._c("1", "As Conciz") + " — select anything, then press "
          + output._c("1", "middle mouse") + f" (or {CONFIG.hotkey}) to explain. "
          + f"Result appears {where}. Ctrl+C to quit.", flush=True)
    global POPUP
    if args.terminal:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            trig.stop()
            print("\nbye")
        return 0
    from consiz.popup import PopupUI, run_app_loop
    POPUP = PopupUI()

    def ask_handler(question: str) -> None:
        from consiz import llm
        output.notify(f"follow-up: {question}")
        msgs = llm.followup_messages(POPUP.context, POPUP.last_answer, question)
        POPUP.show_followup(question, llm.stream_messages(msgs))

    def dictate_handler(ctx: CapturedContext, instruction) -> None:
        lang_str = f" [{instruction.language_name}]" if hasattr(instruction, "language_name") else ""
        output.notify(f"voice instruction{lang_str}: {instruction}")
        res = process_dictation(ctx, instruction)
        POPUP.show_result(res)

    POPUP.on_ask = ask_handler
    POPUP.on_dictate = dictate_handler
    try:
        run_app_loop()
    except KeyboardInterrupt:
        trig.stop()
        print("\nbye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
