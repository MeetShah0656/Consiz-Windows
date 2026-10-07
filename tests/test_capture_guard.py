"""Consiz must never press Ctrl+C where it means 'interrupt the program', nor copy out of password managers."""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows capture")

from consiz.platform.win32 import capture  # noqa: E402


@pytest.mark.parametrize("app", ["cmd.exe", "powershell.exe", "pwsh.exe", "WindowsTerminal.exe", "conhost.exe",
                                 "PuTTY.exe", "mintty.exe", "KeePassXC.exe", "1Password.exe", "Bitwarden.exe"])
def test_no_simulated_copy_in_terminals_or_password_managers(app):
    assert capture.may_simulate_copy(app) is False


@pytest.mark.parametrize("app", ["chrome.exe", "notepad.exe", "WINWORD.EXE", "Code.exe", "explorer.exe"])
def test_normal_apps_still_allow_it(app):
    assert capture.may_simulate_copy(app) is True


def test_capture_in_a_terminal_never_touches_the_keyboard_or_clipboard(monkeypatch):
    monkeypatch.setattr(capture, "frontmost_window_info", lambda: ("WindowsTerminal.exe", "PowerShell", 1))
    monkeypatch.setattr(capture, "uia_selection_probe", lambda: ("", False))   # the app exposes no selection
    monkeypatch.setattr(capture, "clipboard_fallback",
                        lambda: pytest.fail("Ctrl+C must NEVER be simulated in a terminal"))
    monkeypatch.setattr(capture, "_press_ctrl_c", lambda: pytest.fail("Ctrl+C must NEVER be simulated"))
    ctx = capture.capture()
    assert ctx.is_empty and "does not allow copying" in ctx.note


# ------------------------------------------------------------------ speed: do not do slow work for an empty click
def _stub(monkeypatch, app="Brave.exe", probe=("", False)):
    calls = {"browser": 0, "clipboard": 0}
    monkeypatch.setattr(capture, "frontmost_window_info", lambda: (app, "Some page - Brave", 1))
    monkeypatch.setattr(capture, "uia_selection_probe", lambda: probe)
    monkeypatch.setattr(capture, "build_browser_context", lambda *a: calls.__setitem__("browser", calls["browser"] + 1) or {})
    monkeypatch.setattr(capture, "clipboard_fallback", lambda: calls.__setitem__("clipboard", calls["clipboard"] + 1) or ("", []))
    return calls


def test_empty_click_in_a_browser_skips_the_slow_page_scan(monkeypatch):
    calls = _stub(monkeypatch)
    assert capture.capture().is_empty
    assert calls["browser"] == 0                      # ~250 ms of UI-tree walking, only needed when there is text


def test_app_that_reports_an_empty_selection_skips_the_clipboard_fallback_too(monkeypatch):
    calls = _stub(monkeypatch, app="notepad.exe", probe=("", True))
    assert capture.capture().is_empty
    assert calls["clipboard"] == 0                    # nothing to copy: no Ctrl+C, no clipboard churn, ~290 ms saved


def test_app_that_hides_its_selection_still_gets_the_clipboard_fallback(monkeypatch):
    calls = _stub(monkeypatch, app="brave.exe", probe=("", False))
    capture.capture()
    assert calls["clipboard"] == 1


def test_selected_text_still_gets_the_page_context(monkeypatch):
    calls = _stub(monkeypatch, probe=("hello", False))
    monkeypatch.setattr(capture, "build_browser_context", lambda *a: calls.__setitem__("browser", 1) or
                        {"browser": "Brave", "page_title": "T", "url": "u", "domain": "d"})
    ctx = capture.capture()
    assert ctx.raw_content == "hello" and calls["browser"] == 1 and ctx.source_app == "Brave"
