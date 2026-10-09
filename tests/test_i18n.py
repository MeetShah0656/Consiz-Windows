"""Hindi in Consiz's own windows (T-18): the switch works, every sentence the code asks for has a translation, placeholders
survive, and the Hindi windows are not cut off. Real Tk windows (skipped without a display)."""
import ast
import pathlib
import re
import sys
import time

import pytest

from consiz import i18n
from consiz.strings_hi import HI

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEVANAGARI = re.compile("[ऀ-ॿ]")


@pytest.fixture
def hindi(monkeypatch):
    monkeypatch.setenv("CONSIZ_UI_LANGUAGE", "hi")
    i18n.reset()
    yield
    monkeypatch.delenv("CONSIZ_UI_LANGUAGE", raising=False)
    i18n.reset()


@pytest.fixture(autouse=True)
def english_by_default(monkeypatch):
    monkeypatch.setenv("CONSIZ_UI_LANGUAGE", "en")
    i18n.reset()
    yield
    i18n.reset()


# ---------------------------------------------------------------- the switch
def test_english_stays_english_and_hindi_translates(monkeypatch):
    assert i18n.t("Send ➤") == "Send ➤"
    monkeypatch.setenv("CONSIZ_UI_LANGUAGE", "hi")
    i18n.reset()
    assert i18n.t("Send ➤") == "भेजें ➤"
    assert i18n.t("A sentence nobody translated") == "A sentence nobody translated", "no translation shows English, never nothing"
    assert i18n.t("") == "" and i18n.t(None) is None and i18n.t(5) == 5


def test_a_template_is_filled_after_translation(hindi):
    assert "/tmp/x" in i18n.tf("Saved: {path}", path="/tmp/x") and "सहेजा गया" in i18n.tf("Saved: {path}", path="/tmp/x")


def test_surrounding_spaces_and_new_lines_are_kept(hindi):
    assert i18n.tl("\nStopped.\n") == "\nरोक दिया गया।\n"
    assert i18n.tl("   Copy") == "   कॉपी"


def test_the_language_follows_the_setting_and_windows(monkeypatch, tmp_path):
    from consiz import prefs
    monkeypatch.delenv("CONSIZ_UI_LANGUAGE", raising=False)
    monkeypatch.setattr(prefs, "STORE", tmp_path / "p.json")
    monkeypatch.setattr(i18n, "windows_language", lambda: "hi")
    i18n.reset()
    assert i18n.language() == "hi", "Automatic follows a Hindi Windows"
    prefs.set("ui_language", "en")
    i18n.reset()
    assert i18n.language() == "en", "the person's own choice wins"
    prefs.set("ui_language", "klingon")
    i18n.reset()
    assert i18n.language() == "en", "an unknown value is English"


# ---------------------------------------------------------------- the table itself
def test_placeholders_are_identical_in_both_languages():
    names = lambda s: sorted(re.findall(r"\{(\w+)\}", s))        # noqa: E731
    for english, hindi_text in HI.items():
        assert names(english) == names(hindi_text), f"placeholders differ in: {english[:60]!r}"
        assert hindi_text.strip(), f"empty translation for {english[:60]!r}"


def test_line_breaks_and_leading_symbols_match():
    for english, hindi_text in HI.items():
        assert english.count("\n") == hindi_text.count("\n"), f"paragraphs differ in: {english[:60]!r}"
        for symbol in ("✓", "⚠", "▶", "⏸", "⚡", "⬆", "🌐", "🖱", "🗂", "⚙", "🎙", "↺", "■", "➤"):
            assert (symbol in english) == (symbol in hindi_text), f"{symbol} lost or added in: {english[:60]!r}"


def test_every_translation_really_is_hindi_where_it_should_be():
    mostly_latin_ok = {"Windows Consiz never reads inside"}
    for english, hindi_text in HI.items():
        if english in mostly_latin_ok or len(english) < 4:
            continue
        assert DEVANAGARI.search(hindi_text), f"no Hindi in the translation of {english[:60]!r}"


def _translated_calls():
    """Every literal sentence the code passes to t() / tf() / tl() (found by reading the source, not by running it)."""
    found = []
    files = [ROOT / "main.py"] + [p for p in (ROOT / "consiz").rglob("*.py") if "darwin" not in p.parts and p.name != "strings_hi.py"]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if name in ("t", "tf", "tl") and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                found.append((path.relative_to(ROOT).as_posix(), node.lineno, node.args[0].value))
    return found


def test_every_sentence_the_code_translates_has_a_hindi_text():
    calls = _translated_calls()
    assert len(calls) > 60, "the scan found almost nothing: has the code changed shape?"
    missing = [f"{f}:{n}: {text[:70]!r}" for f, n, text in calls if text.strip() and text not in HI and not text.strip() in HI]
    assert not missing, "no Hindi text for:\n" + "\n".join(missing)


# ---------------------------------------------------------------- real windows
@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        from consiz.platform.win32 import popup as pm
        return pm._get_root()
    except tk.TclError:
        pytest.skip("no display available")


def _pump(root, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def _all(widget):
    out = []
    for c in widget.winfo_children():
        out.append(c)
        out += _all(c)
    return out


def _collect_widget_text(root):
    """Every text the main windows give to a widget (English run), via the recorder."""
    from consiz.platform.win32 import popup as pm
    from consiz.platform.win32 import settings as st
    from consiz.platform.win32.login import LoginUI
    from consiz.platform.win32.onboarding import OnboardingUI
    i18n.record = set()
    try:
        ui = pm.PopupUI()
        ui._show_at((100, 100), "Answer", "x")
        ui.open_pc_chat(note="n")
        _pump(root, 0.5)
        ui.window.destroy()
        login = LoginUI()
        login._build()
        login.window.destroy()
        onboarding = OnboardingUI()
        onboarding.show(on_finish=lambda: None)
        for page in range(4):
            onboarding.go(page)
            _pump(root, 0.2)
        onboarding.window.destroy()
        st._OPEN["win"] = None
        st.show_settings_dialog(root)
        win = st._OPEN["win"]
        book = [w for w in win.winfo_children() if w.winfo_class() == "TNotebook"][0]
        for tab in range(5):
            book.select(tab)
            _pump(root, 0.2)
        win.destroy()
        st._OPEN["win"] = None
        return set(i18n.record)
    finally:
        i18n.record = None


# What is deliberately not translated: names, symbols, version numbers and the words used inside tests.
NOT_TRANSLATED = {"Consiz", "tk", "x", "n", "—", "✕", "✦", "◢", "🎙", "Answer", "OpenRouter (uses the key below)"}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_every_text_in_the_main_windows_has_a_hindi_translation(tk_root):
    texts = _collect_widget_text(tk_root)
    assert len(texts) > 100, "the windows were not built"
    missing = sorted(s for s in texts if s not in HI and s not in NOT_TRANSLATED and not s.startswith("Consiz 0.")
                     and not re.fullmatch(r"[\W\d_]*", s) and "gemma" not in s and "OpenRouter key (developer" not in s
                     and "Saved ✓" != s and "ollama pull" not in s)
    assert missing == [], "windows show English because these have no Hindi text:\n" + "\n".join(repr(m) for m in missing)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_the_answer_window_speaks_hindi(tk_root, hindi):
    from consiz.platform.win32 import popup as pm
    ui = pm.PopupUI()
    try:
        ui._show_at((100, 100), "Answer", "x")
        _pump(tk_root)
        assert ui.send_btn.cget("text") == "भेजें ➤" and ui.copy_btn.cget("text") == "सब कॉपी करें"
        ui.open_pc_chat(note="Nothing was selected, so this is Ask about my PC.")
        _pump(tk_root, 0.6)
        chat = ui.chat.get("1.0", "end")
        assert "इस पीसी के बारे में कुछ भी पूछिए" in chat and "मेरा पीसी किस वजह से धीमा हो रहा है?" in chat
        assert "कुछ चुना नहीं गया था" in chat
        ui._set_chat_busy(True)
        assert ui.send_btn.cget("text") == "■ रोकें"
        ui._set_placeholder()
        assert "पीसी" in ui.entry.get("1.0", "end"), "the placeholder in the question box is Hindi too"
    finally:
        ui.window.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_settings_tabs_and_status_line_speak_hindi(tk_root, hindi):
    from consiz.platform.win32 import settings as st
    st._OPEN["win"] = None
    st.show_settings_dialog(tk_root)
    win = st._OPEN["win"]
    try:
        _pump(tk_root, 0.5)
        book = [w for w in win.winfo_children() if w.winfo_class() == "TNotebook"][0]
        assert [book.tab(i, "text") for i in range(5)] == ["सामान्य", "माउस", "शॉर्टकट", "पीसी मोड", "खाता और डेटा"]
    finally:
        win.destroy()
        st._OPEN["win"] = None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_hindi_windows_are_not_cut_off(tk_root, hindi, monkeypatch):
    """Hindi sentences are longer: the answer window, sign-in and welcome windows must still hold all their text."""
    from consiz.platform.win32 import dpi
    from consiz.platform.win32 import popup as pm
    from consiz.platform.win32.login import LoginUI
    from consiz.platform.win32.onboarding import OnboardingUI
    monkeypatch.setattr(dpi, "work_area_at", lambda x, y: (0, 0, 1536, 864))

    def clipped(win):
        win.update_idletasks()
        right, bottom = win.winfo_rootx() + win.winfo_width(), win.winfo_rooty() + win.winfo_height()
        return [(w.winfo_class(), str(w.cget("text"))[:30] if "text" in w.keys() else "") for w in _all(win)
                if w.winfo_ismapped() and w.winfo_width() > 1
                and (w.winfo_rootx() + w.winfo_width() > right + 1 or w.winfo_rooty() + w.winfo_height() > bottom + 1)]

    ui = pm.PopupUI()
    ui.user_size = None
    try:
        ui.open_pc_chat(note="Nothing was selected, so this is Ask about my PC.")
        _pump(tk_root, 0.7)
        assert clipped(ui.window) == []
    finally:
        ui.window.destroy()
    login = LoginUI()
    login._build()
    try:
        _pump(tk_root, 0.4)
        assert clipped(login.window) == []
    finally:
        login.window.destroy()
    onboarding = OnboardingUI()
    onboarding.show(on_finish=lambda: None)
    try:
        for page in range(4):
            onboarding.go(page)
            _pump(tk_root, 0.3)
            assert clipped(onboarding.window) == [], f"welcome page {page + 1}"
    finally:
        onboarding.window.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_tray_texts_and_messages_speak_hindi(hindi):
    pytest.importorskip("pystray")
    from consiz import pc_actions, watcher
    from consiz.platform.win32 import tray
    assert tray.Item("Exit Consiz", None).text == "Consiz बंद करें"
    assert tray.Item(lambda item: "⏸ Pause Consiz", None).text == "⏸ Consiz रोकें"
    act = pc_actions.parse("ACTION: clear_temp", [], [])
    assert act.label == "पुरानी अस्थायी फ़ाइलें साफ़ करें"
    assert pc_actions.parse("ACTION: open_settings storage", [], []).label == "स्टोरेज सेटिंग्स खोलें"
    shown = []
    w = watcher.Watcher(lambda: {"cpu": 99.0, "ram": 10.0, "top": [("chrome.exe", 80.0)]}, lambda title, text: shown.append((title, text)),
                        enabled=lambda: True, hint=lambda: "Ctrl+Alt+A")
    for _ in range(watcher.CPU_TICKS):
        w.tick()
    assert shown[0][0] == "आपका पीसी धीमा है" and "chrome.exe (80%)" in shown[0][1] and "Ctrl+Alt+A" in shown[0][1]
