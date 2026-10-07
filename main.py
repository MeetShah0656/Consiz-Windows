#!/usr/bin/env python3
"""As Conciz — Phase 1 terminal MVP.

Run:   python3 main.py                 # listen for middle-click / hotkey, print results here
       python3 main.py --text "..."    # run the pipeline on given text (no listener)
       python3 main.py --path FILE     # run the pipeline on a file or folder
       python3 main.py --capture       # capture the current selection once and process it
"""
from __future__ import annotations

import argparse
import os
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


def _login_needed() -> bool:
    """True (and opens the sign-in window) when auth is configured but nobody is signed in."""
    from consiz import auth
    if POPUP is None or not auth.enabled() or auth.signed_in():
        return False
    from consiz.platform.win32.popup import _dispatch
    from consiz.platform.win32.login import open_login
    output.notify("sign in required — opening the sign-in window")
    _dispatch(open_login)
    return True


def on_trigger(source: str) -> None:
    if _login_needed():
        return
    from consiz.capture import capture
    output.notify(f"trigger: {source}")
    ctx = capture()
    output.notify(f"captured {ctx.size_bytes} bytes from {ctx.source_app} via {ctx.capture_method.value.lower()} — processing…")
    if ctx.is_empty and POPUP is not None and sys.platform == "win32":
        # Nothing selected: instead of a dead-end error, offer to look at the PC (it asks permission first).
        if on_pc_trigger("nothing-selected", note="Nothing was selected, so this is Ask about my PC."):
            return
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


def _pc_mode_consent() -> bool:
    """First use only: say plainly what PC mode reads and sends, and remember the answer."""
    from consiz import prefs
    if prefs.get("pc_mode_consent"):
        return True
    if sys.platform != "win32":
        return True
    import ctypes
    msg = ("Ask about my PC will look at, on this computer:" + chr(10) + "  - names of running programs and how much "
           "memory/CPU they use" + chr(10) + "  - titles of open windows (not what is inside them)" + chr(10)
           + "  - disk space, battery, startup programs" + chr(10) + chr(10)
           + "When you ask a question, this summary (with passwords/keys removed) is sent to the AI to answer you. "
           "Nothing is changed on your PC." + chr(10) + chr(10) + "Allow this?")
    if ctypes.windll.user32.MessageBoxW(None, msg, "Consiz - Ask about my PC", 0x24) != 6:   # YES/NO + question icon
        return False
    prefs.set("pc_mode_consent", True)
    return True


def _read_window(hwnd: int) -> tuple[str, str]:
    from consiz.platform.win32.readwin import read_window_text
    return read_window_text(hwnd)


def _capture_window_image(hwnd: int):
    from consiz.platform.win32.readwin import capture_window_jpeg_b64
    return capture_window_jpeg_b64(hwnd)


def _confirm_window_read(titles: list[str]) -> bool:
    """Layer 3 permission: name the exact windows before any text inside them is read or sent."""
    import ctypes
    nl = chr(10)
    msg = ("Consiz wants to read the text inside:" + nl + nl + nl.join("  - " + t[:90] for t in titles) + nl + nl
           + "This text (passwords and keys removed) is sent to the AI to answer your question. "
           "If an app (like a browser) does not share its text, a PICTURE of that window is sent instead "
           "- a picture cannot have secrets removed, so say No if anything private is on that window."
           + nl + nl + "Nothing is changed or sent anywhere else. Allow for this session?")
    return ctypes.windll.user32.MessageBoxW(None, msg, "Consiz - read window text", 0x24) == 6


def on_pc_trigger(source: str, note: str = "") -> bool:
    """Hotkey/tray: open the 'Ask about my PC' chat (no selection needed). True if the chat was opened."""
    if _login_needed():
        return True                                   # the sign-in window is showing instead
    if not _pc_mode_consent():
        output.notify("PC mode was not allowed")
        return False
    output.notify(f"PC mode: {source}")
    if POPUP is None:
        return False
    POPUP.open_pc_chat(note=note)
    return True


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

    def _report_health() -> None:
        ok, msg = llm.health()
        output.notify(("✓ " if ok else "✗ ") + msg)

    one_shot = bool(args.text is not None or args.path or args.capture or args.dictate)
    if one_shot:
        _report_health()
    else:   # the listener must not wait on the network (a sleeping server can take 30-50 s to answer)
        threading.Thread(target=_report_health, daemon=True, name="health-check").start()

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
        if sys.platform == "win32":   # the exe has no console: without this the click would look dead
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                "Consiz is already running.\n\n"
                "Look for its icon in the system tray (click the ^ arrow near the clock). "
                "Right-click it for the menu.\n\n"
                "To use it: select text, then press the middle mouse button.",
                "Consiz", 0x40)
        return 1

    from consiz.trigger import Trigger
    # Dictation hotkey temporarily disabled (not yet part of the shared Mac feature
    # set — see As-Conciz/20-For-Meet-What-Consiz-Does-Today-Plain-Words.md). Backend
    # (on_dictate_trigger, run_terminal_dictation, consiz/dictation.py) is untouched —
    # passing on_dictate=on_dictate_trigger here re-enables it.
    trig = Trigger(
        on_trigger,
        on_busy=lambda: output.notify("still working on the previous request — wait a moment"),
        **({"on_pc": on_pc_trigger} if sys.platform == "win32" else {}),
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
        if POPUP.mode == "pc":
            from consiz import pc_mode
            from consiz.platform.win32.popup import _dispatch
            try:
                text, summary = pc_mode.get_context()
            except Exception as e:
                raise llm.LLMError(f"could not read the PC: {e}")
            _dispatch(POPUP._set_meta, f"Looked at: {summary} · {time.strftime('%H:%M:%S')}")
            stream = pc_mode.stream_answer(
                question, list(POPUP.history), text, pc_mode.last_windows(),
                stream_fn=llm.stream_messages, read_text=_read_window, confirm=_confirm_window_read,
                notify=lambda m: _dispatch(POPUP._set_meta, m), capture_image=_capture_window_image)
            POPUP.show_followup(question, stream)
            return
        msgs = llm.chat_messages(POPUP.context, POPUP.last_answer, list(POPUP.history), question)
        POPUP.show_followup(question, llm.stream_messages(msgs))

    def dictate_handler(ctx: CapturedContext, instruction) -> None:
        lang_str = f" [{instruction.language_name}]" if hasattr(instruction, "language_name") else ""
        output.notify(f"voice instruction{lang_str}: {instruction}")
        res = process_dictation(ctx, instruction)
        POPUP.show_result(res)

    def _reopen_login() -> None:
        from consiz.platform.win32.login import open_login
        open_login()

    POPUP.on_auth_needed = _reopen_login
    POPUP.on_ask = ask_handler
    POPUP.on_dictate = dictate_handler

    from consiz import prefs

    def _ensure_login() -> None:
        from consiz import auth
        if not auth.enabled():
            return
        from consiz.platform.win32.popup import _dispatch

        def _check():                     # network check off the UI thread; then show login if needed
            auth.revalidate()
            _dispatch(_login_needed)
        threading.Thread(target=_check, daemon=True).start()

    def _dispatch_login() -> None:
        from consiz.platform.win32.popup import _dispatch
        from consiz.platform.win32.login import open_login
        _dispatch(open_login)

    def _sign_out() -> None:
        from consiz import auth
        from consiz.platform.win32.popup import _dispatch
        auth.sign_out()
        output.notify("signed out")
        _dispatch(_login_needed)

    if not prefs.get("onboarding_completed"):
        from consiz.platform.win32.onboarding import open_onboarding
        open_onboarding(on_finish=_ensure_login)
    else:
        _ensure_login()

    if sys.platform == "win32":
        try:
            from consiz import auth as _auth
            auth_on = _auth.enabled()
            from consiz.platform.win32.tray import SystemTray
            from consiz.platform.win32.settings import show_settings_dialog

            def _open_settings():
                if POPUP and getattr(POPUP, "window", None):
                    POPUP.window.after(0, lambda: show_settings_dialog(POPUP.window))
                else:
                    show_settings_dialog()

            tray = SystemTray(
                on_explain=lambda src: on_trigger(src),
                on_dictate=lambda src: on_dictate_trigger(src),
                on_settings=_open_settings,
                on_exit=lambda: os._exit(0),
                on_pc=lambda src: on_pc_trigger(src),
                on_sign_out=_sign_out if auth_on else None,
                get_user_label=(lambda: ("Signed in: " + _auth.display_name()) if _auth.signed_in()
                                else "Not signed in") if auth_on else None,
                is_signed_in=_auth.signed_in if auth_on else None,
                on_sign_in=(lambda: _dispatch_login()) if auth_on else None,
                welcome="Select any text, then press the middle mouse button.",
            )
            tray.start()
        except Exception as e:
            output.notify(f"Tray notice: {e}")

    try:
        run_app_loop()
    except KeyboardInterrupt:
        trig.stop()
        print("\nbye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
