"""Saved chats (T-13): off by default, local only, secrets removed, replayable, deletable, exportable as text. Real Tk windows
for the popup parts (skipped without a display). The settings file is private per test (tests/conftest.py)."""
import json
import time

import pytest

from consiz import history, prefs

TRANSCRIPT = [["Consiz", "- The mouse trigger is on Keyboard only."], ["You", "how do I change it?"],
              ["Consiz", "- Settings > Mouse."]]


@pytest.fixture
def on(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "STORE", tmp_path / "prefs.json")
    prefs.set("history_enabled", True)
    return tmp_path


def _save(chat_id="20261009-120000-ab12", transcript=TRANSCRIPT, started=None):
    return history.save(chat_id, "selection", "Explained", "claude.exe", transcript, started or time.time())


# ---------------------------------------------------------------- the rules
def test_nothing_is_saved_unless_the_person_turned_it_on(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "STORE", tmp_path / "prefs.json")
    assert history.enabled() is False
    assert _save() is False
    assert not (tmp_path / "history").exists() or not list((tmp_path / "history").glob("*.json"))


def test_a_chat_is_saved_with_its_words_and_a_title_from_the_first_question(on):
    assert _save() is True
    rec = history.load("20261009-120000-ab12")
    assert [m["who"] for m in rec["messages"]] == ["Consiz", "You", "Consiz"]
    assert rec["title"] == "how do I change it?" and rec["mode"] == "selection" and rec["app"] == "claude.exe"


def test_a_chat_without_any_answer_is_not_worth_saving(on):
    assert _save(transcript=[["You", "hello"]]) is False
    assert _save(transcript=[["Consiz", ""]]) is False


def test_secrets_are_removed_before_anything_is_written(on):
    key = "sk-or-v1-" + "a1b2c3d4" * 4
    _save(transcript=[["Consiz", f"- Your key {key} is exposed"], ["You", "my card is 4111 1111 1111 1111"]])
    raw = (on / "history" / "20261009-120000-ab12.json").read_text(encoding="utf-8")
    assert key not in raw and "4111 1111 1111 1111" not in raw


def test_saving_again_updates_the_same_file(on):
    _save(transcript=TRANSCRIPT[:1])
    _save(transcript=TRANSCRIPT)
    assert history.count() == 1 and len(history.load("20261009-120000-ab12")["messages"]) == 3


def test_recent_lists_newest_first_and_the_oldest_are_pruned(on, monkeypatch):
    monkeypatch.setattr(history, "MAX_CHATS", 5)
    for n in range(8):
        _save(chat_id=f"2026100{n + 1}-120000-000{n}", transcript=[["Consiz", f"- answer {n}"], ["You", f"question {n}"]])
    assert history.count() == 5
    titles = [c["title"] for c in history.recent(10)]
    assert titles == ["question 7", "question 6", "question 5", "question 4", "question 3"]


def test_only_real_chat_ids_can_be_opened(on):
    _save()
    assert history.load("20261009-120000-ab12") is not None
    for bad in ("../prefs", "..\\prefs", "20261009-120000-ab12.json", "", "x" * 40, "C:\\Windows\\win.ini"):
        assert history.load(bad) is None, bad


def test_a_damaged_file_is_ignored_not_fatal(on):
    _save()
    (on / "history" / "20261009-130000-cd34.json").write_text("{ not json", encoding="utf-8")
    assert [c["id"] for c in history.recent(10)] == ["20261009-120000-ab12"]


def test_delete_all_removes_every_saved_chat(on):
    _save()
    _save(chat_id="20261009-130000-cd34")
    assert history.delete_all() == 2 and history.count() == 0 and history.recent() == []


def test_clearing_local_data_also_clears_saved_chats(on):
    from consiz import localdata
    _save()
    done = localdata.clear_local_data()
    assert history.count() == 0 and any("saved chats" in d for d in done)


# ---------------------------------------------------------------- the text file
def test_a_chat_can_be_saved_as_text_even_with_history_off(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "STORE", tmp_path / "prefs.json")
    key = "sk-or-v1-" + "a1b2c3d4" * 4
    path = history.export_text(TRANSCRIPT + [["You", f"is {key} safe?"]], "Explained", "claude.exe", time.time(),
                               where=tmp_path / "out")
    text = path.read_text(encoding="utf-8")
    assert path.suffix == ".txt" and "how do I change it" in path.name
    assert "Consiz:\n- The mouse trigger" in text and "You:\nhow do I change it?" in text and key not in text


# ---------------------------------------------------------------- the popup
@pytest.fixture
def popup_env(on):
    tk = pytest.importorskip("tkinter")
    try:
        from consiz.platform.win32 import popup as pm
        root = pm._get_root()
    except tk.TclError:
        pytest.skip("no display available")
    return pm, root


def _pump(root, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def _talk(ui):
    ui._show_at((100, 100), "Explained", "claude.exe")
    ui._begin_ai()
    ui._append("- The mouse trigger is on Keyboard only.")
    ui._add_user("how do I change it?")
    ui._begin_ai()
    ui._append("- Settings > Mouse.")


def test_the_popup_saves_the_conversation_when_it_is_closed_and_starts_a_new_file_for_a_new_chat(popup_env):
    pm, root = popup_env
    ui = pm.PopupUI()
    try:
        _talk(ui)
        ui.hide()
        _pump(root)
        first_id = ui._chat_id
        assert first_id and history.load(first_id)["messages"][1]["text"] == "how do I change it?"
        ui.new_chat()
        _talk(ui)
        ui._save_history()
        assert ui._chat_id != first_id and history.count() == 2
    finally:
        ui.window.destroy()


def test_nothing_is_written_while_history_is_off(popup_env):
    pm, root = popup_env
    prefs.set("history_enabled", False)
    ui = pm.PopupUI()
    try:
        _talk(ui)
        ui.hide()
        _pump(root)
        assert history.count() == 0
    finally:
        ui.window.destroy()


def test_a_saved_chat_can_be_opened_again_and_carried_on(popup_env):
    pm, root = popup_env
    first = pm.PopupUI()
    try:
        _talk(first)
        first._save_history()
        record = history.load(first._chat_id)
    finally:
        first.window.destroy()
    ui = pm.PopupUI()
    try:
        ui._reopen(record, (100, 100))
        _pump(root)
        assert [who for who, _ in ui._transcript] == ["Consiz", "You", "Consiz"]
        assert ui.last_answer == "- The mouse trigger is on Keyboard only."
        assert ui.history == [{"role": "user", "content": "how do I change it?"},
                              {"role": "assistant", "content": "- Settings > Mouse."}], "later turns become the follow-up history"
        assert ui._chat_id == record["id"], "carrying on writes to the same file"
    finally:
        ui.window.destroy()


def test_save_as_text_from_the_window(popup_env, monkeypatch, tmp_path):
    pm, root = popup_env
    ui = pm.PopupUI()
    monkeypatch.setattr(history.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(pm.subprocess, "Popen", lambda *a, **k: None)               # do not open Explorer in a test
    try:
        _talk(ui)
        ui._export_text()
        files = list((tmp_path / "Documents" / "Consiz chats").glob("*.txt"))
        assert len(files) == 1 and "Settings > Mouse." in files[0].read_text(encoding="utf-8")
        assert ui.meta_lbl.cget("text").startswith("Saved:")
    finally:
        ui.window.destroy()


# ---------------------------------------------------------------- the tray menu and Settings
def test_the_tray_menu_lists_saved_chats_or_says_why_it_is_empty(on):
    pytest.importorskip("pystray")
    from consiz.platform.win32 import tray
    opened = []
    texts = lambda: [i.text for i in tray.history_menu_items(opened.append) if getattr(i, "text", None)]    # noqa: E731
    assert texts()[0] == "No saved chats yet"
    _save(transcript=[["Consiz", "- a"], ["You", "Fish & chips?"]])
    items = list(tray.history_menu_items(opened.append))
    assert any("Fish && chips?" in i.text for i in items if hasattr(i, "text")), "an ampersand is doubled so the menu shows it"
    prefs.set("history_enabled", False)
    assert "off" in texts()[0].lower()


def test_settings_has_the_chat_history_switch_off_by_default(popup_env):
    pm, root = popup_env
    from consiz.platform.win32 import settings as st
    st._OPEN["win"] = None
    prefs.set("history_enabled", False)
    st.show_settings_dialog(root)
    win = st._OPEN["win"]
    try:
        _pump(root, 0.5)

        def labels(w):
            found = []
            for c in w.winfo_children():
                try:
                    found.append(str(c.cget("text")))
                except Exception:
                    pass
                found += labels(c)
            return found

        text = " | ".join(labels(win))
        assert "Chat history" in text and "Keep my chats on this PC" in text and "Delete all saved chats" in text
    finally:
        win.destroy()
        st._OPEN["win"] = None
