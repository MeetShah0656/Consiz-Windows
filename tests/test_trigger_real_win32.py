"""The hotkey registration against the REAL Windows API (no fake): register, release on pause, re-register on resume,
move to a new key. Uses odd key combos so it cannot collide with a running Consiz, never installs the mouse hook and
never sends a click, so it does not touch the desktop."""
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def _wait(cond, seconds=4.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


@pytest.fixture
def real_trigger(monkeypatch):
    from consiz import pause
    from consiz.config import CONFIG
    from consiz.platform.win32 import trigger as tr
    monkeypatch.setenv("CONSIZ_TRIGGER_MODE", "hotkey")             # keyboard only: no mouse hook is installed
    monkeypatch.setattr(CONFIG, "hotkey", "<ctrl>+<alt>+<shift>+<f11>")
    monkeypatch.setattr(CONFIG, "pc_hotkey", "<ctrl>+<alt>+<shift>+<f12>")
    monkeypatch.setattr(CONFIG, "dictate_hotkey", "")
    pause.set_paused(False)
    trig = tr.Trigger(lambda s: None, on_pc=lambda s: None)
    trig.start()
    assert _wait(lambda: trig._native_ready.is_set())
    yield tr, trig, CONFIG, pause
    pause.set_paused(False)
    trig.stop()
    time.sleep(0.2)


def test_real_hotkeys_register_release_on_pause_and_come_back(real_trigger):
    tr, trig, CONFIG, pause = real_trigger
    if set(trig._registered) != {"hotkey", "pc"}:
        pytest.skip("another program already holds these test shortcuts")
    assert trig._mouse_hook is None, "keyboard-only mode must not hook the mouse"

    pause.set_paused(True)                                          # wakes the pump thread, which releases the keys
    assert _wait(lambda: not trig._registered), "paused: the shortcuts must be released to the apps"
    # while released, another program can take the very same shortcut: proof they are really free
    mods, vk = tr.parse_hotkey_to_win32(CONFIG.hotkey)
    assert tr.user32.RegisterHotKey(None, 0xC0F0, mods, vk), "the key is free while Consiz is paused"
    tr.user32.UnregisterHotKey(None, 0xC0F0)

    pause.set_paused(False)
    assert _wait(lambda: set(trig._registered) == {"hotkey", "pc"}), "resume: the shortcuts come back"
    assert not tr.user32.RegisterHotKey(None, 0xC0F1, mods, vk), "…and Consiz holds the key again"


def test_real_hotkey_moves_when_settings_change_it(real_trigger):
    tr, trig, CONFIG, pause = real_trigger
    if set(trig._registered) != {"hotkey", "pc"}:
        pytest.skip("another program already holds these test shortcuts")
    CONFIG.hotkey = "<ctrl>+<alt>+<shift>+<f10>"                    # what Settings > Shortcuts does
    trig._wake_pump()                                               # the 3 s watchdog does the same on its own
    assert _wait(lambda: trig._registered.get("hotkey", (0, ""))[1] == "<ctrl>+<alt>+<shift>+<f10>")
    old_mods, old_vk = tr.parse_hotkey_to_win32("<ctrl>+<alt>+<shift>+<f11>")
    assert tr.user32.RegisterHotKey(None, 0xC0F2, old_mods, old_vk), "the old shortcut was released"
    tr.user32.UnregisterHotKey(None, 0xC0F2)
