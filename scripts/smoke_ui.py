"""Smoke test of the PACKAGED app: does the exe really start, show its first window on screen, stay alive and write a clean
log? It runs a throw-away copy with its own empty settings folder and its own single-instance lock, so it never touches
the Consiz you are using (your settings, your sign-in, your running copy). Only the process it started is stopped.

    python scripts/smoke_ui.py                          # dist\\Consiz\\Consiz.exe
    python scripts/smoke_ui.py --exe C:\\build\\Consiz\\Consiz.exe --voice
    python scripts/smoke_ui.py --wait 40                # slow PC / antivirus scanning the exe

--voice also has the exe transcribe a sentence spoken by Windows' own voice (needs the speech model on this PC).
Exit code 0 = every check passed, 1 = something failed. Windows only.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIRST_WINDOWS = ("Welcome to Consiz", "Sign in to Consiz")          # what a brand-new profile opens first
RESULTS: list[tuple[str, str, str]] = []


def record(status: str, name: str, evidence: str = "") -> None:
    RESULTS.append((status, name, evidence))
    print(f"[{status:4}] {name}" + (f" - {evidence}" if evidence else ""), flush=True)


def windows_of(pid: int) -> list[tuple[str, tuple[int, int, int, int], int]]:
    """(title, (left, top, right, bottom), handle) of the visible top-level windows that belong to `pid`."""
    user32 = ctypes.windll.user32
    found: list = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append((buf.value, (r.left, r.top, r.right, r.bottom), hwnd))
        return True

    user32.EnumWindows(each, 0)
    return found


def work_area() -> tuple[int, int, int, int]:
    r = wt.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)       # SPI_GETWORKAREA
    return r.left, r.top, r.right, r.bottom


def speak_to_wav(text: str, path: Path) -> bool:
    """Windows' own voice reads `text` into a .wav file (no internet, no cost)."""
    script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{text}'); $s.Dispose()")
    p = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=60)
    return p.returncode == 0 and path.exists() and path.stat().st_size > 1000


def check_starts(exe: Path, wait: float, sandbox: Path) -> None:
    env = dict(os.environ, CONSIZ_STATE_DIR=str(sandbox), CONSIZ_INSTANCE_SUFFIX="-smoke-" + uuid.uuid4().hex[:8])
    proc = subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env)
    try:
        wins, deadline = [], time.time() + wait
        while time.time() < deadline and proc.poll() is None:
            wins = [w for w in windows_of(proc.pid) if w[0].startswith(FIRST_WINDOWS)]
            if wins:
                break
            time.sleep(0.5)
        if proc.poll() is not None:
            record("FAIL", "exe starts and stays running", f"exited with code {proc.poll()}")
            return
        record("PASS", "exe starts and stays running", f"alive after {time.time() - (deadline - wait):.1f} s")
        if not wins:
            record("FAIL", "first window appears", f"no '{FIRST_WINDOWS[0]}' window within {wait:.0f} s")
        else:
            title, (left, top, right, bottom), hwnd = wins[0]
            wl, wtop, wr, wb = work_area()
            inside = left >= wl and top >= wtop and right <= wr and bottom <= wb
            record("PASS" if inside else "FAIL", f"'{title}' is fully on the screen",
                   f"window {right - left}x{bottom - top} at ({left},{top}); usable area {wr - wl}x{wb - wtop}")
            record("PASS" if right - left >= 300 and bottom - top >= 300 else "FAIL", "first window has a sensible size",
                   f"{right - left}x{bottom - top}")
            hung = bool(ctypes.windll.user32.IsHungAppWindow(hwnd))
            record("FAIL" if hung else "PASS", "first window responds", "not responding" if hung else "answers Windows' pings")
        try:
            import psutil
            mb = psutil.Process(proc.pid).memory_info().rss / 1024 / 1024
            record("PASS" if mb < 400 else "WARN", "memory at start", f"{mb:.0f} MB")
        except Exception:
            pass
    finally:
        proc.terminate()                                        # only the process started here, never by name
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
    log = sandbox / "consiz.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    bad = [ln for ln in text.splitlines() if " CRITICAL " in ln or "Traceback" in ln or " ERROR " in ln]
    record("PASS" if "starting" in text and not bad else "FAIL", "log has a start line and no errors",
           (bad[0][:140] if bad else ("log not written" if not text else "clean")))


def check_voice(exe: Path, sandbox: Path) -> None:
    sys.path.insert(0, str(ROOT))
    try:
        from consiz import voice
        if not voice.model_cached():
            record("SKIP", "voice: exe hears a spoken sentence", f"speech model '{voice.model_name()}' is not on this PC")
            return
    except Exception as e:
        record("SKIP", "voice: exe hears a spoken sentence", f"cannot check the model ({type(e).__name__})")
        return
    wav = sandbox / "spoken.wav"
    if not speak_to_wav("Hello Consiz, what is slowing my computer down", wav):
        record("SKIP", "voice: exe hears a spoken sentence", "Windows' voice could not make the test sound")
        return
    t = time.time()
    p = subprocess.run([str(exe), "--voice-selftest", str(wav)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300, env=dict(os.environ, CONSIZ_STATE_DIR=str(sandbox),
                                                                CONSIZ_INSTANCE_SUFFIX="-smoke-voice"))
    heard = (p.stdout or "").lower()
    ok = p.returncode == 0 and "slowing" in heard
    record("PASS" if ok else "FAIL", "voice: exe hears a spoken sentence",
           f"{time.time() - t:.1f} s; " + ((p.stdout or p.stderr or "no output").strip().splitlines() or [""])[-1][:120])


def main() -> int:
    if sys.platform != "win32":
        print("smoke_ui.py runs on Windows only")
        return 1
    ctypes.windll.user32.SetProcessDPIAware()                   # real pixels, so window sizes can be compared with the screen
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=str(ROOT / "dist" / "Consiz" / "Consiz.exe"))
    ap.add_argument("--wait", type=float, default=25.0, help="seconds to wait for the first window")
    ap.add_argument("--voice", action="store_true", help="also check speech-to-text inside the exe")
    args = ap.parse_args()
    exe = Path(args.exe)
    if not exe.exists():
        print(f"no exe at {exe}: build it first (python build_exe.py)")
        return 1
    sandbox = Path(tempfile.mkdtemp(prefix="consiz-smoke-"))
    try:
        check_starts(exe, args.wait, sandbox)
        if args.voice:
            check_voice(exe, sandbox)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\nRESULT: {'FAILED' if fails else 'OK'}  ({len(RESULTS) - len(fails)} passed or skipped, {len(fails)} failed)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
