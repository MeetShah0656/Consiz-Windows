"""Administrator windows (T-16): Consiz cannot read them, and must say so instead of "nothing selected"."""
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_our_own_process_is_reported_correctly():
    from consiz.platform.win32 import elevation
    from consiz.platform.win32.priority import is_admin
    assert elevation.process_is_elevated(os.getpid()) is is_admin()


def test_a_normal_program_is_not_an_administrator_window():
    import subprocess
    from consiz.platform.win32 import elevation
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        from consiz.platform.win32.priority import is_admin
        assert elevation.process_is_elevated(child.pid) is is_admin()          # same rights as the test run, whatever they are
    finally:
        child.kill()


def test_the_process_of_a_missing_window_is_unknown_not_an_error():
    from consiz.platform.win32 import elevation
    assert elevation.process_is_elevated(4_000_000) is None
    assert elevation.window_needs_admin(0) is False


def test_an_administrator_window_gets_a_clear_note_instead_of_silence(monkeypatch):
    from consiz.platform.win32 import capture, elevation
    monkeypatch.setattr(capture, "frontmost_window_info", lambda: ("regedit.exe", "Registry Editor", 77))
    monkeypatch.setattr(capture, "uia_selection_probe", lambda: ("", True))
    monkeypatch.setattr(elevation, "window_needs_admin", lambda hwnd: hwnd == 77)
    ctx = capture.capture()
    assert ctx.is_empty and "regedit.exe" in ctx.note and "administrator" in ctx.note and "Run as administrator" in ctx.note


def test_an_ordinary_window_with_nothing_selected_has_no_such_note(monkeypatch):
    from consiz.platform.win32 import capture, elevation
    monkeypatch.setattr(capture, "frontmost_window_info", lambda: ("notepad.exe", "Untitled", 78))
    monkeypatch.setattr(capture, "uia_selection_probe", lambda: ("", True))
    monkeypatch.setattr(elevation, "window_needs_admin", lambda hwnd: False)
    assert capture.capture().note == ""


def test_relaunching_a_packaged_exe_as_administrator_does_not_pass_its_own_path(monkeypatch):
    from consiz.platform.win32 import priority
    seen = {}

    class FakeShell:
        def ShellExecuteW(self, hwnd, verb, file, params, cwd, show):
            seen.update(verb=verb, file=file, params=params)
            return 5                                                           # refused: stay in the test

    monkeypatch.setattr(priority, "is_admin", lambda: False)
    monkeypatch.setattr(priority, "shell32", FakeShell())
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", [r"C:\Apps\Consiz\Consiz.exe", "--elevate"])
    priority.request_admin_elevation()
    assert seen["verb"] == "runas" and seen["params"] == '"--elevate"'
