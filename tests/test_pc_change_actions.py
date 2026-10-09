"""Confirm-first PC actions (T-12): close a program, clear old temp files, stop a startup item. Nothing happens without a
Yes, Windows' own programs are refused, and only old files in a folder named Temp are ever deleted."""
import os
import subprocess
import sys
import time

import pytest

from consiz import pc_actions

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
psutil = pytest.importorskip("psutil")

WINDOWS = [{"hwnd": 111, "title": "Spotify Premium", "app": "Spotify.exe"},
           {"hwnd": 222, "title": "Untitled - Notepad", "app": "notepad.exe"}]
STARTUP = ["OneDrive", "Spotify", "Discord"]
BS = chr(92)


# ---------------------------------------------------------------- what the AI may name
def test_the_ai_can_name_each_change_action_only_with_valid_numbers():
    p = pc_actions.parse
    assert p("ACTION: end_program 2", WINDOWS, STARTUP).kind == "end_program"
    assert p("ACTION: end_program 2", WINDOWS, STARTUP).target == "222"
    assert p("ACTION: end_program 9", WINDOWS, STARTUP) is None and p("ACTION: end_program", WINDOWS, STARTUP) is None
    assert p("ACTION: clear_temp", WINDOWS, STARTUP).kind == "clear_temp"
    assert p("ACTION: clear_temp C:" + BS + "Windows", WINDOWS, STARTUP) is None, "no path can be smuggled in"
    a = p("ACTION: disable_startup S2", WINDOWS, STARTUP)
    assert a.kind == "disable_startup" and a.target == "Spotify"
    assert p("ACTION: disable_startup 3", WINDOWS, STARTUP).target == "Discord"
    assert p("ACTION: disable_startup S9", WINDOWS, STARTUP) is None and p("ACTION: disable_startup S1", WINDOWS, None) is None
    assert p("ACTION: delete_file C:" + BS + "x", WINDOWS, STARTUP) is None


def test_the_three_change_actions_need_a_confirmation_and_the_others_do_not():
    for text in ("end_program 1", "clear_temp", "disable_startup S1"):
        assert pc_actions.needs_confirm(pc_actions.parse("ACTION: " + text, WINDOWS, STARTUP))
    for text in ("open_task_manager", "open_settings storage", "focus_window 1"):
        assert not pc_actions.needs_confirm(pc_actions.parse("ACTION: " + text, WINDOWS, STARTUP))


def test_a_change_action_does_nothing_without_a_confirm_function():
    ok, msg = pc_actions.run(pc_actions.Action("clear_temp", "", "x"))
    assert not ok and "confirmation" in msg
    ok, msg = pc_actions.run(pc_actions.Action("end_program", "123", "x"))
    assert not ok and "confirmation" in msg


# ---------------------------------------------------------------- ending a program
def _sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def test_a_program_is_not_touched_when_the_answer_is_no():
    from consiz.platform.win32 import actions
    child = _sleeper()
    try:
        ok, msg = actions._end_process(psutil.Process(child.pid), "t", lambda title, text: False)
        assert not ok and "Nothing was changed" in msg and child.poll() is None
    finally:
        child.kill()


def test_a_stuck_program_is_force_stopped_only_after_a_second_yes():
    from consiz.platform.win32 import actions
    child = _sleeper()                                            # no window: it can never close by itself
    asked = []
    try:
        ok, msg = actions._end_process(psutil.Process(child.pid), "t",
                                       lambda title, text: asked.append(title) or True, wait_s=0.5)
        assert ok and msg == "Stopped." and len(asked) == 2 and "force" in asked[1].lower()
        assert child.wait(5) is not None
    finally:
        child.kill()


def test_saying_no_to_the_force_question_leaves_it_running():
    from consiz.platform.win32 import actions
    child = _sleeper()
    answers = iter([True, False])
    try:
        ok, msg = actions._end_process(psutil.Process(child.pid), "t", lambda title, text: next(answers), wait_s=0.5)
        assert not ok and "Left running" in msg and child.poll() is None
    finally:
        child.kill()


class _FakeProc:
    def __init__(self, name, exe, user="me", pid=999_001):
        self.pid, self._name, self._exe, self._user = pid, name, exe, user

    def name(self):
        return self._name

    def exe(self):
        return self._exe

    def username(self):
        return self._user


@pytest.mark.parametrize("name,exe", [
    ("svchost.exe", "C:" + BS + "Windows" + BS + "System32" + BS + "svchost.exe"),
    ("explorer.exe", "C:" + BS + "Windows" + BS + "explorer.exe"),
    ("MsMpEng.exe", "C:" + BS + "ProgramData" + BS + "Defender" + BS + "MsMpEng.exe"),
    ("csrss.exe", ""),
    ("Consiz.exe", "C:" + BS + "Apps" + BS + "Consiz" + BS + "Consiz.exe"),
    ("notepad.exe", "C:" + BS + "Windows" + BS + "System32" + BS + "notepad.exe"),
])
def test_windows_own_programs_and_security_software_are_refused_and_never_asked_about(name, exe):
    from consiz.platform.win32 import actions
    ok, msg = actions._end_process(_FakeProc(name, exe), "t", lambda *a: pytest.fail("must not even ask"))
    assert not ok and "will not close this" in msg


def test_consiz_and_the_program_that_started_it_are_refused():
    from consiz.platform.win32 import actions
    assert actions.protected_reason(psutil.Process(os.getpid()))
    parent = psutil.Process(os.getpid()).parent()
    if parent is not None:
        assert actions.protected_reason(parent)


def test_another_users_program_is_refused():
    from consiz.platform.win32 import actions
    me = psutil.Process(os.getpid()).username()
    exe = "C:" + BS + "Apps" + BS + "chrome.exe"
    assert actions.protected_reason(_FakeProc("chrome.exe", exe, user="OTHER" + BS + "someone")) == "it belongs to another account"
    assert actions.protected_reason(_FakeProc("chrome.exe", exe, user=me)) is None


# ---------------------------------------------------------------- clearing temporary files
def _make(tmp, name, age_hours, size=1000):
    p = tmp / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    _set_times(p, time.time() - age_hours * 3600)
    return p


def _set_times(path, when):
    """Windows keeps a creation time too, and the app counts a file as old only if BOTH are old: set all three."""
    import pywintypes
    import win32con
    import win32file
    stamp = pywintypes.Time(when)
    handle = win32file.CreateFile(str(path), win32con.GENERIC_WRITE, 0, None, win32con.OPEN_EXISTING,
                                  win32con.FILE_ATTRIBUTE_NORMAL, None)
    try:
        win32file.SetFileTime(handle, stamp, stamp, stamp)
    finally:
        handle.Close()


def test_only_files_more_than_a_day_old_are_listed_and_deleted_after_a_yes(tmp_path):
    from consiz.platform.win32 import actions
    root = tmp_path / "AppData" / "Local" / "Temp"
    old1, old2 = _make(root, "a.tmp", 30), _make(root, "sub/b.tmp", 72, 5000)
    new = _make(root, "fresh.tmp", 2)
    seen = []
    ok, msg = actions.clear_temp(lambda title, text: seen.append(text) or True, root=str(root))
    assert ok and not old1.exists() and not old2.exists() and new.exists()
    assert "2 temporary files" in seen[0] and str(root) in seen[0] and "Recycle Bin" in seen[0]
    assert "Deleted 2 files" in msg and not (root / "sub").exists(), "the emptied folder is tidied up"


def test_nothing_is_deleted_on_no_and_nothing_to_clear_asks_nothing(tmp_path):
    from consiz.platform.win32 import actions
    root = tmp_path / "AppData" / "Local" / "Temp"
    old = _make(root, "a.tmp", 30)
    ok, msg = actions.clear_temp(lambda *a: False, root=str(root))
    assert not ok and old.exists() and "Nothing was changed" in msg
    old.unlink()
    _make(root, "fresh.tmp", 1)
    ok, msg = actions.clear_temp(lambda *a: pytest.fail("nothing to ask about"), root=str(root))
    assert ok and "Nothing to clear" in msg


def test_only_a_folder_named_temp_can_be_cleared(tmp_path):
    from consiz.platform.win32 import actions
    docs = tmp_path / "Documents"
    old = _make(docs, "thesis.docx", 500)
    ok, msg = actions.clear_temp(lambda *a: pytest.fail("must refuse before asking"), root=str(docs))
    assert not ok and "named Temp" in msg and old.exists()
    ok, msg = actions.clear_temp(lambda *a: pytest.fail("never a drive root"), root="C:" + BS)
    assert not ok


def test_a_junction_inside_temp_is_never_followed(tmp_path):
    from consiz.platform.win32 import actions
    root = tmp_path / "AppData" / "Local" / "Temp"
    root.mkdir(parents=True)
    precious = tmp_path / "Documents"
    keep = _make(precious, "keep.docx", 900)
    link = root / "link"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(precious)], capture_output=True)
    if made.returncode != 0:
        pytest.skip("cannot create a junction here")
    _make(root, "old.tmp", 50)
    ok, msg = actions.clear_temp(lambda *a: True, root=str(root))
    assert ok and keep.exists(), "files behind a junction must survive"


# ---------------------------------------------------------------- startup items
def test_a_startup_item_is_switched_off_the_way_task_manager_does_it():
    import winreg
    from consiz.platform.win32 import actions
    run_key, approved = "Software" + BS + "ConsizTest" + BS + "Run", "Software" + BS + "ConsizTest" + BS + "StartupApproved" + BS + "Run"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key) as k:
            winreg.SetValueEx(k, "FakeApp", 0, winreg.REG_SZ, "C:" + BS + "fake" + BS + "app.exe")
        asked = []
        ok, msg = actions.disable_startup("FakeApp", lambda title, text: asked.append(text) or False, run_key, approved)
        assert not ok and "Nothing was changed" in msg
        ok, msg = actions.disable_startup("FakeApp", lambda title, text: asked.append(text) or True, run_key, approved)
        assert ok and "FakeApp" in asked[0] and "turn it back on" in asked[0]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, approved) as k:
            value, kind = winreg.QueryValueEx(k, "FakeApp")
        assert kind == winreg.REG_BINARY and len(value) == 12 and value[0] == 3, "03 00 00 00 + time = disabled"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as k:
            assert winreg.QueryValueEx(k, "FakeApp")[0].endswith("app.exe"), "the entry itself is not deleted"
    finally:
        for sub in (approved, run_key, "Software" + BS + "ConsizTest" + BS + "StartupApproved", "Software" + BS + "ConsizTest"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass


def test_an_all_users_startup_item_opens_settings_instead_of_changing_anything(monkeypatch):
    from consiz.platform.win32 import actions
    opened = []
    monkeypatch.setattr(actions, "launch", lambda target: opened.append(target) or (True, "Opened."))
    ok, msg = actions.disable_startup("NotInThisUsersList", lambda *a: pytest.fail("no change, no question"),
                                      "Software" + BS + "ConsizTest" + BS + "DoesNotExist",
                                      "Software" + BS + "ConsizTest" + BS + "X")
    assert ok and opened == ["ms-settings:startupapps"] and "all users" in msg


# ---------------------------------------------------------------- the snapshot gives the AI numbers to name
def test_pc_snapshot_numbers_the_startup_items_for_the_ai():
    from consiz import pc_mode
    snap = {"taken_at": "now", "system": {"cpu_percent": 5, "cpu_cores": 4, "ram_used_gb": 4, "ram_total_gb": 8,
            "ram_percent": 50, "process_count": 100, "uptime_hours": 1, "disks": [], "battery": None},
            "apps": [], "windows": [], "startup": ["OneDrive", "Spotify"], "network": None}
    text, _ = pc_mode.render(snap)
    assert "[S1] OneDrive, [S2] Spotify" in text


# ---------------------------------------------------------------- the popup button asks before it changes anything
def test_clicking_a_change_button_in_the_chat_goes_through_the_confirm_box(monkeypatch):
    tk = pytest.importorskip("tkinter")
    try:
        from consiz.platform.win32 import popup as pm
        root = pm._get_root()
    except tk.TclError:
        pytest.skip("no display available")
    from consiz.platform.win32 import actions
    ui = pm.PopupUI()
    calls = []
    monkeypatch.setattr(actions, "clear_temp", lambda confirm: calls.append(confirm("title", "text")) or (True, "done"))
    ui.on_confirm_action = lambda title, text: True
    try:
        ui._show_at((100, 100), "PC", "x")
        act = pc_actions.parse("ACTION: clear_temp", [], [])
        ui._add_action(act)
        tag = f"act{ui._action_n}"
        ui._run_action(act, tag)
        end = time.time() + 3
        while time.time() < end and not calls:
            root.update()
            time.sleep(0.02)
        assert calls == [True], "the box was asked and its Yes was passed to the action"
    finally:
        ui.window.destroy()
