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
import time

from consiz import llm, output
from consiz.config import CONFIG
from consiz.models import CapturedContext, CaptureMethod
from consiz.router import process


def run_once(ctx: CapturedContext) -> None:
    output.notify(f"captured {ctx.size_bytes} bytes from {ctx.source_app} via {ctx.capture_method.value.lower()} — processing…")
    output.render(process(ctx))


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


def main() -> int:
    ap = argparse.ArgumentParser(description="As Conciz terminal MVP")
    ap.add_argument("--text", help="process this text instead of listening")
    ap.add_argument("--path", help="process this file/folder instead of listening")
    ap.add_argument("--capture", action="store_true", help="capture current selection once, process, exit")
    ap.add_argument("--provider", choices=["openrouter", "ollama"], default=CONFIG.provider)
    ap.add_argument("--model", default=None, help="override model id for the chosen provider")
    ap.add_argument("--no-stream", action="store_true")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--terminal", action="store_true", help="print results in the terminal instead of the popup window")
    ap.add_argument("--hotkey", default=CONFIG.hotkey, help="keyboard fallback, pynput syntax (e.g. '<ctrl>+<alt>+s')")
    args = ap.parse_args()
    CONFIG.provider, CONFIG.hotkey = args.provider, args.hotkey
    if args.model:
        if args.provider == "ollama":
            CONFIG.ollama_model = args.model
        else:
            CONFIG.openrouter_model = args.model
    CONFIG.stream, CONFIG.color = not args.no_stream, not args.no_color

    ok, msg = llm.health()
    output.notify(("✓ " if ok else "✗ ") + msg)

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

    from consiz.trigger import Trigger
    trig = Trigger(on_trigger, on_busy=lambda: output.notify("still working on the previous request — wait a moment"))
    trig.start()
    where = "in the terminal" if args.terminal else "in a popup next to your selection"
    print(output._c("1", "As Conciz") + " — select anything, then press the "
          + output._c("1", "middle mouse button") + f" (or {CONFIG.hotkey}). Result appears {where}. Ctrl+C to quit.")
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

    POPUP.on_ask = ask_handler
    try:
        run_app_loop()
    except KeyboardInterrupt:
        trig.stop()
        print("\nbye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
