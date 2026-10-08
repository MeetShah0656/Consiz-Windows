"""T-09: the logic behind the Settings window (hotkeys, clear local data, PC-mode lists, live hotkey changes, popup size)
plus smoke tests that the real windows build in server mode and in developer mode."""
import pytest

from consiz import hotkeys, localdata, pc_mode, pause, prefs


@pytest.fixture
def state(tmp_path, monkeypatch):
    """Preferences and log in a temp folder, never the user's own."""
    from consiz import logs
    monkeypatch.setattr(prefs, "STORE", tmp_path / "prefs.json")
    monkeypatch.setattr(logs, "LOG_FILE", tmp_path / "consiz.log")
    return tmp_path


# ---------------------------------------------------------------- hotkeys
@pytest.mark.parametrize("text,expected", [
    ("Ctrl+Alt+S", "<ctrl>+<alt>+s"),
    ("ctrl + alt + a", "<ctrl>+<alt>+a"),
    ("<ctrl>+<alt>+s", "<ctrl>+<alt>+s"),
    ("alt+ctrl+7", "<ctrl>+<alt>+7"),
    ("Ctrl+Shift+Space", "<ctrl>+<shift>+<space>"),
    ("Win+Alt+K", "<alt>+<cmd>+k"),
    ("Ctrl+F9", "<ctrl>+<f9>"),
    ("Alt+F12", "<alt>+<f12>"),
])
def test_valid_shortcuts_are_normalised(text, expected):
    assert hotkeys.normalize(text) == expected


@pytest.mark.parametrize("text", ["", "S", "Ctrl+S", "Ctrl+C", "Alt+Tab", "Ctrl+Alt", "Ctrl+Alt+S+D", "F9",
                                  "Shift+A", "Ctrl+Alt+Delete", "Ctrl+Alt+F25", "Ctrl+Alt+;", "banana"])
def test_dangerous_or_broken_shortcuts_are_refused(text):
    assert hotkeys.normalize(text) is None


def test_pretty_hotkey_is_what_a_person_reads():
    assert hotkeys.pretty("<ctrl>+<alt>+s") == "Ctrl+Alt+S"
    assert hotkeys.pretty("<ctrl>+<f9>") == "Ctrl+F9"
    assert hotkeys.pretty("<alt>+<cmd>+k") == "Alt+Win+K"
    assert hotkeys.normalize(hotkeys.pretty("<ctrl>+<shift>+<space>")) == "<ctrl>+<shift>+<space>"


# ---------------------------------------------------------------- clear local data
def test_clear_local_data_removes_ours_and_keeps_the_users_profile(state, monkeypatch):
    from consiz import auth, logs
    profile = state / "profile.md"
    profile.write_text("my own words", encoding="utf-8")
    prefs.set("onboarding_completed", True)
    logs.LOG_FILE.write_text("log line", encoding="utf-8")
    (state / "consiz.log.1").write_text("old", encoding="utf-8")
    monkeypatch.setattr(auth, "enabled", lambda: False)
    done = localdata.clear_local_data()
    assert not prefs.STORE.exists() and not logs.LOG_FILE.exists() and not (state / "consiz.log.1").exists()
    assert profile.read_text(encoding="utf-8") == "my own words"
    assert any("prefs.json" in d for d in done)
    assert prefs.get("onboarding_completed") is None, "the welcome screens come back"


def test_clear_local_data_signs_out_first(state, monkeypatch):
    from consiz import auth
    calls = []
    monkeypatch.setattr(auth, "enabled", lambda: True)
    monkeypatch.setattr(auth, "signed_in", lambda: True)
    monkeypatch.setattr(auth, "sign_out", lambda: calls.append("out"))
    assert any("signed out" in d for d in localdata.clear_local_data())
    assert calls == ["out"]


def test_clear_local_data_with_nothing_to_clear_is_quiet(state, monkeypatch):
    from consiz import auth
    monkeypatch.setattr(auth, "enabled", lambda: False)
    assert localdata.clear_local_data() == []


# ---------------------------------------------------------------- PC mode lists
def test_users_own_never_read_words_block_windows(state):
    win = {"title": "Quarterly numbers - Project Phoenix", "app": "excel.exe"}
    assert pc_mode.sensitive_reason(win) is None
    prefs.set("pc_blocklist_words", ["phoenix", " Tally "])
    assert "own never-read list" in pc_mode.sensitive_reason(win)
    assert "own never-read list" in pc_mode.sensitive_reason({"title": "Ledger", "app": "tally.exe"})
    assert pc_mode.sensitive_reason({"title": "Notes", "app": "notepad.exe"}) is None
    assert pc_mode.sensitive_reason({"title": "My password list", "app": "notepad.exe"}) is not None   # built-in rule still on


def test_blocklist_accepts_a_plain_string_and_junk(state):
    prefs.set("pc_blocklist_words", "alpha, beta,, ")
    assert pc_mode.user_blocklist() == ["alpha", "beta"]
    prefs.set("pc_blocklist_words", None)
    assert pc_mode.user_blocklist() == []


def test_forget_allowed_windows_asks_again(state):
    pc_mode._allowed.update({1, 2})
    pc_mode._read_cache[(1, "t")] = ("x", None, 0.0)
    pc_mode.forget_allowed_windows()
    assert not pc_mode._allowed and not pc_mode._read_cache


# ---------------------------------------------------------------- live hotkeys (fake Windows)
class _FakeUser32:
    def __init__(self):
        self.held = {}                               # id -> (mods, vk)
        self.refuse = set()

    def RegisterHotKey(self, hwnd, hk_id, mods, vk):
        if hk_id in self.refuse:
            return 0
        self.held[hk_id] = (mods, vk)
        return 1

    def UnregisterHotKey(self, hwnd, hk_id):
        self.held.pop(hk_id, None)
        return 1


@pytest.fixture
def trig(monkeypatch):
    from consiz.config import CONFIG
    from consiz.platform.win32 import trigger as tr
    fake = _FakeUser32()
    monkeypatch.setattr(tr, "user32", fake)
    monkeypatch.setattr(CONFIG, "hotkey", "<ctrl>+<alt>+s")
    monkeypatch.setattr(CONFIG, "pc_hotkey", "<ctrl>+<alt>+a")
    pause.set_paused(False)
    t = tr.Trigger(lambda s: None, on_pc=lambda s: None)
    yield tr, t, fake, CONFIG
    pause.set_paused(False)


def test_hotkeys_are_taken_then_released_while_paused(trig):
    tr, t, fake, _ = trig
    t._sync_hotkeys()
    assert set(fake.held) == {tr.HOTKEY_ID, tr.HOTKEY_PC_ID}
    pause.set_paused(True)
    t._sync_hotkeys()
    assert fake.held == {}, "paused: the app in front gets Ctrl+Alt+S itself"
    pause.set_paused(False)
    t._sync_hotkeys()
    assert set(fake.held) == {tr.HOTKEY_ID, tr.HOTKEY_PC_ID}


def test_changing_a_shortcut_in_settings_moves_the_registration(trig):
    tr, t, fake, CONFIG = trig
    t._sync_hotkeys()
    old = fake.held[tr.HOTKEY_ID]
    CONFIG.hotkey = "<ctrl>+<alt>+j"
    t._sync_hotkeys()
    assert fake.held[tr.HOTKEY_ID] != old and fake.held[tr.HOTKEY_ID][1] == ord("J")
    assert fake.held[tr.HOTKEY_PC_ID][1] == ord("A"), "the other shortcut is untouched"


def test_a_shortcut_taken_by_another_app_is_retried_not_fatal(trig):
    tr, t, fake, _ = trig
    fake.refuse = {tr.HOTKEY_ID}
    t._sync_hotkeys()
    assert tr.HOTKEY_ID not in fake.held and "hotkey" not in t._native_registered
    fake.refuse = set()                              # the other app let go
    t._sync_hotkeys()
    assert tr.HOTKEY_ID in fake.held and "hotkey" in t._native_registered


# ---------------------------------------------------------------- popup size memory (KI-13)
def test_popup_size_is_remembered_at_100_percent_scale(state, monkeypatch):
    from consiz.platform.win32 import popup as pm
    monkeypatch.setenv("CONSIZ_UI_SCALE", "1.25")
    ui = pm.PopupUI.__new__(pm.PopupUI)
    ui.user_size = (600, 750)
    ui._save_size()
    assert prefs.get("popup_size") == [480, 600]
    assert pm._load_size() == (600, 750)
    monkeypatch.setenv("CONSIZ_UI_SCALE", "1")       # same saved value on a 100 % screen
    assert pm._load_size() == (480, 600)


@pytest.mark.parametrize("bad", [None, "x", [1], ["a", "b"], 5])
def test_broken_saved_size_means_default(state, bad):
    from consiz.platform.win32 import popup as pm
    prefs.set("popup_size", bad)
    assert pm._load_size() is None


def test_saved_size_is_kept_within_sane_limits(state):
    from consiz.platform.win32 import popup as pm
    prefs.set("popup_size", [5, 99999])
    w, h = pm._load_size()
    assert w >= 320 and h <= 1600 * 2


# ---------------------------------------------------------------- real windows build (hidden)
@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        from consiz.platform.win32 import popup as pm
        root = pm._get_root()
    except tk.TclError:
        pytest.skip("no display available")
    return root


@pytest.mark.parametrize("server", [True, False])
def test_settings_window_builds_in_both_modes(tk_root, state, monkeypatch, server):
    from consiz import llm
    from consiz.platform.win32 import settings as st
    monkeypatch.setattr(llm, "server_mode", lambda: server)
    st._OPEN["win"] = None
    st.show_settings_dialog(tk_root)
    win = st._OPEN["win"]
    win.withdraw()
    try:
        texts = []

        def walk(w):
            try:
                texts.append(str(w.cget("text")))
            except Exception:
                pass
            for c in w.winfo_children():
                walk(c)
        walk(win)
        joined = "\n".join(texts)
        assert ("OpenRouter API key" in joined) is (not server), "end users must never be asked for an AI key"
        for needed in ("Answer language", "Pause Consiz now", "Explain selection", "Forget my permission", "Clear local data…"):
            assert needed in joined
    finally:
        st._OPEN["win"] = None
        win.destroy()


def test_settings_opens_once_not_twice(tk_root, state):
    from consiz.platform.win32 import settings as st
    st._OPEN["win"] = None
    st.show_settings_dialog(tk_root)
    first = st._OPEN["win"]
    first.withdraw()
    st.show_settings_dialog(tk_root)
    assert st._OPEN["win"] is first
    st._OPEN["win"] = None
    first.destroy()


def test_welcome_ai_page_does_not_ask_end_users_for_a_key(tk_root, state, monkeypatch):
    from consiz import llm
    from consiz.platform.win32 import onboarding as ob
    monkeypatch.setattr(llm, "server_mode", lambda: True)
    ui = ob.OnboardingUI()
    ui._build()
    ui.window.withdraw()
    try:
        ui.go(2)
        tk_root.update()
        assert not ui._key_entry.winfo_ismapped(), "no OpenRouter key box for end users"
        assert "sign in with Google" in ui.ai_status.cget("text")
    finally:
        ui.window.destroy()
