#!/usr/bin/env python3
"""Consiz — Phase 1 terminal MVP.

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
        # CONSIZ_INSTANCE_SUFFIX lets scripts/smoke_ui.py run a throw-away copy next to the real one without touching it.
        name = "Local\\ConsizSingleInstanceMutex" + os.environ.get("CONSIZ_INSTANCE_SUFFIX", "")
        _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(None, False, name)
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
    print(f"🎙 Dictated ({res.language_name} ~{res.language_probability:.0%}): \"{res.text}\" — processing…", flush=True)
    output.notify("dictation transcribed — processing…")
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


_LOGIN_PROMPTED_AT = [0.0]


def on_trigger(source: str):
    """Returns "passthrough" when a MIDDLE CLICK should go back to the app it was meant for (T-01)."""
    if source == "middle-click" and time.time() - _LOGIN_PROMPTED_AT[0] < 120:
        from consiz import auth
        if auth.enabled() and not auth.signed_in():
            return "passthrough"                      # already asked for sign-in a moment ago: do not nag
    if _login_needed():
        _LOGIN_PROMPTED_AT[0] = time.time()
        return None
    from consiz.capture import capture
    output.notify(f"trigger: {source}")
    t_cap = time.perf_counter()
    ctx = capture()
    output.notify(f"captured {ctx.size_bytes} bytes from {ctx.source_app} via {ctx.capture_method.value.lower()} "
                  f"in {(time.perf_counter() - t_cap) * 1000:.0f} ms — processing…")
    if ctx.is_empty and POPUP is not None and sys.platform == "win32":
        if source == "middle-click":
            # A plain middle click with nothing selected is NOT for Consiz (open link, close tab, autoscroll):
            # hand it back to the app instead of showing an error.
            output.notify("nothing selected — click passed through to the app")
            return "passthrough"
        # Keyboard hotkey with nothing selected: offer to look at the PC (it asks permission first).
        pic = _picture_on_clipboard(ctx)
        if pic is not None:
            POPUP.show_result(pic)
            return
        why = ctx.note if "administrator" in (ctx.note or "") else "Nothing was selected, so this is Ask about my PC."
        if on_pc_trigger("nothing-selected", note=why):
            return
    res = process(ctx)
    if POPUP is not None:
        POPUP.show_result(res)
    else:
        output.render(res)


def _confirm_picture(label: str) -> bool:
    """Asked EVERY time a picture would be sent to the AI: private details in a picture cannot be removed first."""
    if sys.platform != "win32":
        return False
    import ctypes
    msg = ("Consiz can explain this picture with the AI:" + chr(10) + chr(10) + "  " + label[:90] + chr(10) + chr(10)
           + "The picture itself is sent (shrunk), and passwords or other private details in a picture cannot be removed "
           "first. Nothing is stored." + chr(10) + chr(10) + "Send it?")
    return ctypes.windll.user32.MessageBoxW(None, msg, "Consiz - explain a picture", 0x124) == 6      # Yes/No, No is the default


import consiz.router as _router                    # noqa: E402 - the router asks this box before it sends a picture file
_router.PICTURE_CONSENT = _confirm_picture

_DECLINED_PICTURE: list = [None]          # the clipboard picture the person already said no to: do not ask again for it


def _picture_on_clipboard(ctx):
    """Shortcut pressed with nothing selected while a picture (a screenshot) is on the clipboard: offer to explain it.
    Returns a Result, or None to carry on (no picture, or the person said no)."""
    if sys.platform != "win32" or "administrator" in (ctx.note or ""):
        return None
    import hashlib
    from consiz.platform.win32.capture import clipboard_picture
    img = clipboard_picture()
    if img is None:
        return None
    fingerprint = (img.size, hashlib.md5(img.tobytes()).hexdigest())
    if fingerprint == _DECLINED_PICTURE[0]:
        return None
    if not _confirm_picture("the picture on your clipboard (for example a screenshot), " + f"{img.size[0]}x{img.size[1]}"):
        _DECLINED_PICTURE[0] = fingerprint
        return None
    from consiz import router
    return router.picture_result(img, "picture from the clipboard", ctx.source_app)


def _confirm_change(title: str, text: str) -> bool:
    """The Yes/No box for actions that CHANGE the PC (close a program, delete old temp files, stop a startup item).
    Warning icon, No is the default, and it stays on top of the answer window."""
    if sys.platform != "win32":
        return False
    import ctypes
    return ctypes.windll.user32.MessageBoxW(None, text, title, 0x40134) == 6      # YESNO | WARNING | default No | topmost


def _reopen_saved_chat(chat_id: str) -> None:
    """Tray > Recent chats: show a saved chat again (T-13)."""
    from consiz import history
    record = history.load(chat_id)
    if record is None or POPUP is None:
        output.notify(f"saved chat {chat_id} could not be opened")
        return
    POPUP.reopen_chat(record)


_VOICE_CANCEL = threading.Event()


def _notice(text: str) -> None:
    """A plain message box (voice problems can happen before any Consiz window is open)."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Consiz - Voice dictation", 0x40)
    else:
        output.notify(text)


def _voice_consent(model: str, mb: int) -> bool:
    """First use only: the speech model is not inside the app. Say what it is, how big, where it goes - and ask."""
    if sys.platform != "win32":
        return True
    import ctypes
    nl = chr(10)
    msg = (f"Voice dictation needs a one-time download of the speech model (about {mb} MB) from Hugging Face." + nl + nl
           + "It is kept on this PC. Your voice is turned into text on this PC and the audio is never uploaded; "
           "only the words you say are sent to the AI, like a typed question." + nl + nl + "Download it now?")
    return ctypes.windll.user32.MessageBoxW(None, msg, "Consiz - Voice dictation", 0x24) == 6   # YES/NO + question icon


def _voice_ready() -> bool:
    """Worker thread: make sure dictation can start now (model on this PC, or download it with the user's OK)."""
    from consiz import voice

    def progress(text: str) -> None:
        if POPUP is not None:
            from consiz.platform.win32.popup import _dispatch
            _dispatch(POPUP._set_meta, text)
        output.notify(text)

    _VOICE_CANCEL.clear()
    ok, why = voice.prepare(_voice_consent, progress, _VOICE_CANCEL)
    if not ok and why:
        _notice(why)
    return ok


def on_dictate_trigger(source: str) -> None:
    """Ctrl+Alt+D (or the tray item): with text selected, speak what to do with it; with nothing selected, speak a
    question about this PC. Pressing it again while listening stops at once (it also stops by itself after a pause)."""
    from consiz.capture import capture
    output.notify(f"dictate trigger: {source}")
    if POPUP is not None and POPUP.is_listening():
        output.notify("stopping dictation (shortcut pressed again)")
        POPUP.stop_dictation()
        return
    if _login_needed():
        return
    ctx = capture()                                   # first: the selection must be read before any box takes focus
    output.notify(f"captured {ctx.size_bytes} bytes from {ctx.source_app} via {ctx.capture_method.value.lower()} - starting dictation")
    if POPUP is None:
        run_terminal_dictation(ctx)
        return
    if not _voice_ready():
        return
    from consiz.platform.win32.popup import _dispatch
    if ctx.is_empty:
        if not _pc_mode_consent():
            return
        POPUP.open_pc_chat(note="Nothing was selected, so speak a question about this PC.")
        _dispatch(POPUP.begin_voice_question)
    else:
        POPUP.start_dictation_flow(ctx)


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
    from consiz import __version__, logs
    logs.setup()
    logs.get().info("Consiz %s starting (%s)", __version__, "exe" if getattr(sys, "frozen", False) else "source")
    if sys.platform == "win32":
        from consiz.platform.win32 import dpi
        dpi.enable()                                  # sharp text on 125 % / 150 % screens; before any window exists (T-06)
        logs.get().info("screen scale %.2f", dpi.scale())
    ap = argparse.ArgumentParser(description="Consiz terminal MVP")
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
    ap.add_argument("--voice-selftest", metavar="WAVFILE", help="transcribe a recorded .wav with the speech model, print the words, exit")
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

    if args.voice_selftest:
        return _voice_selftest(args.voice_selftest)
    one_shot = bool(args.text is not None or args.path or args.capture or args.dictate)
    if not one_shot:
        llm.start_keepalive()
    if one_shot:
        _report_health()
    else:   # the listener must not wait on the network (a sleeping server can take 30-50 s to answer)
        threading.Thread(target=_report_health, daemon=True, name="health-check").start()

    # The speech model is loaded when dictation is first used (voice.prepare), not at start-up.

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
    # Voice dictation (Ctrl+Alt+D) is on for Windows: speech is turned into text on this PC (faster-whisper).
    trig = Trigger(
        on_trigger,
        on_busy=lambda: output.notify("still working on the previous request — wait a moment"),
        **({"on_pc": on_pc_trigger, "on_dictate": on_dictate_trigger} if sys.platform == "win32" else {}),
    )
    trig.start()
    where = "in the terminal" if args.terminal else "in a popup next to your selection"
    print(output._c("1", "Consiz") + " — select anything, then press "
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
        output.notify(f"follow-up question ({len(question)} chars)")
        if POPUP.mode == "pc":
            from consiz import pc_mode
            from consiz.platform.win32.popup import _dispatch
            try:
                text, summary = pc_mode.get_context()
            except Exception as e:
                raise llm.LLMError(f"could not read the PC: {e}")
            tok = llm.current_token()
            if tok is not None:
                tok.check()                             # Stop was pressed while the PC snapshot was being taken
            _dispatch(POPUP._set_meta, f"Looked at: {summary} · {time.strftime('%H:%M:%S')}")
            stream = pc_mode.stream_answer(
                question, list(POPUP.history), text, pc_mode.last_windows(),
                stream_fn=llm.stream_messages, read_text=_read_window, confirm=_confirm_window_read,
                notify=lambda m: _dispatch(POPUP._set_meta, m), capture_image=_capture_window_image)
            POPUP.show_followup(question, stream)
            return
        from consiz import pictures
        msgs = llm.chat_messages(POPUP.context, POPUP.last_answer, list(POPUP.history), question,
                                 images=pictures.remembered(POPUP.context))     # a chat about a picture can still see it
        POPUP.show_followup(question, llm.stream_messages(msgs))

    def dictate_handler(ctx: CapturedContext, instruction) -> None:
        lang_str = f" [{instruction.language_name}]" if hasattr(instruction, "language_name") else ""
        output.notify(f"voice instruction received{lang_str}")
        res = process_dictation(ctx, instruction)
        POPUP.show_result(res)

    def _reopen_login() -> None:
        from consiz.platform.win32.login import open_login
        open_login()

    POPUP.on_auth_needed = _reopen_login
    POPUP.on_ask = ask_handler
    POPUP.on_dictate = dictate_handler
    POPUP.on_voice_prepare = _voice_ready
    POPUP.on_confirm_action = _confirm_change

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
                kw = dict(on_sign_out=_sign_out if auth_on else None,
                          on_reset_popup=lambda: setattr(POPUP, "user_size", None))
                if POPUP and getattr(POPUP, "window", None):
                    POPUP.window.after(0, lambda: show_settings_dialog(POPUP.window, **kw))
                else:
                    show_settings_dialog(**kw)

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
                on_open_chat=_reopen_saved_chat,
            )
            tray.start()
            from consiz import hotkeys as _hotkeys, watcher as _watcher
            from consiz.platform.win32.sysinfo import quick_sample
            _watcher.Watcher(
                quick_sample, lambda title, text: tray.icon is not None and tray.icon.notify(text, title),
                enabled=lambda: bool(prefs.get("watcher_enabled", False)),
                hint=lambda: _hotkeys.pretty(CONFIG.pc_hotkey)).start()
            if llm.server_mode():
                from consiz import updater

                def _on_update(info: dict) -> None:
                    """Tell the user ONCE per version; the tray menu keeps a Download item after that."""
                    key = "update_required" if info["required"] else info["latest"]
                    if prefs.get("update_notified") == key or tray.icon is None:
                        return
                    prefs.set("update_notified", key)
                    tray.icon.update_menu()
                    tray.icon.notify("This version is no longer supported. Right-click the tray icon > Download update."
                                     if info["required"] else
                                     f"Consiz {info['latest']} is available. Right-click the tray icon > Download.",
                                     "Consiz update")

                updater.start_background_check(_on_update)
        except Exception as e:
            output.notify(f"Tray notice: {e}")

    try:
        run_app_loop()
    except KeyboardInterrupt:
        trig.stop()
        print("\nbye")
    return 0


def _voice_selftest(path: str) -> int:
    """For support and for checking a packaged build: speech file in, words out (uses the speech model already on this PC)."""
    import wave

    import numpy as np
    from consiz import voice
    from consiz.dictation import DictationEngine
    if not voice.available():
        print("voice: NOT INCLUDED in this build")
        return 2
    if not voice.model_cached():
        print(f"voice: speech model '{voice.model_name()}' is not on this PC yet")
        return 3
    with wave.open(path) as w:
        sr, ch, raw = w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        audio = np.interp(np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / sr)), np.arange(len(audio)), audio).astype(np.float32)
    res = DictationEngine().transcribe(audio)
    print(f"voice: heard {res.text!r} ({res.language_name}, {res.language_probability:.0%})")
    return 0 if res.text else 1


def _fatal(exc: BaseException) -> int:
    from consiz import logs
    logs.get().critical("FATAL: Consiz stopped", exc_info=(type(exc), exc, exc.__traceback__))
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, "Consiz hit an unexpected error and had to stop." + chr(10) + chr(10) + "Details were saved to:"
            + chr(10) + str(logs.LOG_FILE) + chr(10) + chr(10) + "Please send that file to support.", "Consiz", 0x10)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(0)
    except BaseException as _e:                      # noqa: BLE001 - last line of defence
        sys.exit(_fatal(_e))
