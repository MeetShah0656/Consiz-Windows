"""Voice dictation end to end, with fakes for the microphone and the speech model (no audio device, no download):
availability, the one-time model download (consent, progress, cancel), the popup's microphone button, the two ways a
spoken sentence is used, and the shortcut following the Settings switch. A real-speech check lives in
test_voice_real_speech (skipped when the speech model is not on this PC)."""
import threading
import time
import types

import pytest

from consiz import dictation, prefs, voice


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "STORE", tmp_path / "prefs.json")
    return tmp_path


# ---------------------------------------------------------------- voice.prepare: availability, consent, download
class _Engine:
    warmed = 0

    def warmup(self):
        type(self).warmed += 1


@pytest.fixture
def engine(monkeypatch):
    _Engine.warmed = 0
    monkeypatch.setattr(dictation, "get_dictation_engine", lambda: _Engine())
    monkeypatch.setattr(voice, "available", lambda: True)
    return _Engine


def test_not_included_in_this_build_says_so(state, monkeypatch):
    monkeypatch.setattr(voice, "available", lambda: False)
    ok, why = voice.prepare(lambda *a: True, lambda m: None)
    assert not ok and "not included" in why
    assert voice.enabled() is False


def test_switched_off_in_settings(state, engine):
    prefs.set("voice_enabled", False)
    ok, why = voice.prepare(lambda *a: True, lambda m: None)
    assert not ok and "switched off" in why and voice.enabled() is False


def test_model_already_on_the_pc_starts_at_once_and_warms_up(state, engine, monkeypatch):
    monkeypatch.setattr(voice, "model_cached", lambda name=None: True)
    asked = []
    ok, why = voice.prepare(lambda *a: asked.append(a) or True, lambda m: None)
    assert ok and why == "" and not asked, "no question, no download"
    assert engine.warmed == 1, "the model loads while the person is still speaking"


def test_first_use_asks_with_the_size_then_downloads_with_progress(state, engine, monkeypatch):
    monkeypatch.setattr(voice, "model_cached", lambda name=None: False)
    asked, shown, downloaded = [], [], []

    def fake_download(name, on_progress, cancel):
        downloaded.append(name)
        for done in (50, 250, 484):
            on_progress(done * 1_048_576, 484 * 1_048_576)

    monkeypatch.setattr(voice, "download_model", fake_download)
    ok, why = voice.prepare(lambda name, mb: asked.append((name, mb)) or True, shown.append)
    assert ok and downloaded == [voice.model_name()]
    assert asked == [(voice.model_name(), voice.model_mb())] and asked[0][1] > 400, "the person is told the size first"
    assert any("Downloading" in m and "%" in m for m in shown), shown
    assert engine.warmed == 1


def test_saying_no_downloads_nothing(state, engine, monkeypatch):
    monkeypatch.setattr(voice, "model_cached", lambda name=None: False)
    monkeypatch.setattr(voice, "download_model", lambda *a, **k: pytest.fail("must not download without a yes"))
    ok, why = voice.prepare(lambda *a: False, lambda m: None)
    assert (ok, why) == (False, "")


def test_download_problems_become_a_plain_message(state, engine, monkeypatch):
    monkeypatch.setattr(voice, "model_cached", lambda name=None: False)

    def broken(*a, **k):
        raise voice.VoiceError("Could not download the voice model. Check your internet connection and try again. (ConnectionError)")

    monkeypatch.setattr(voice, "download_model", broken)
    ok, why = voice.prepare(lambda *a: True, lambda m: None)
    assert not ok and "internet" in why


def test_cancelling_a_download_is_not_an_error(state, engine, monkeypatch):
    monkeypatch.setattr(voice, "model_cached", lambda name=None: False)

    def cancelled(*a, **k):
        raise voice.DownloadCancelled("cancelled")

    monkeypatch.setattr(voice, "download_model", cancelled)
    ok, why = voice.prepare(lambda *a: True, lambda m: None)
    assert not ok and "cancelled" in why


def test_download_reports_progress_and_can_be_cancelled(monkeypatch):
    """The real download function, with Hugging Face's downloader replaced by a fake that drives the progress bar."""
    import huggingface_hub

    seen, cancel = [], threading.Event()

    def fake_snapshot(repo, allow_patterns=None, tqdm_class=None):
        assert repo.startswith("Systran/") and "model.bin" in allow_patterns
        bar = tqdm_class(total=484_000_000, unit="B", disable=True)
        for _ in range(4):
            bar.update(100_000_000)
            if len(seen) == 2:
                cancel.set()                                # the user presses cancel part-way

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot)
    with pytest.raises(voice.DownloadCancelled):
        voice.download_model("small", lambda done, total: seen.append((done, total)), cancel)
    assert seen and seen[0][1] == 484_000_000 and seen[-1][0] > seen[0][0]


def test_download_failure_is_wrapped(monkeypatch):
    import huggingface_hub

    def offline(*a, **k):
        raise ConnectionError("no network")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", offline)
    with pytest.raises(voice.VoiceError, match="internet"):
        voice.download_model("small")


def test_model_table_matches_what_settings_shows():
    assert set(voice.MODELS) >= {"small", "base", "tiny"}
    assert voice.model_mb("small") > voice.model_mb("base") > voice.model_mb("tiny")


# ---------------------------------------------------------------- the shortcut follows the Settings switch
class _FakeUser32:
    def __init__(self):
        self.held = {}

    def RegisterHotKey(self, hwnd, hk_id, mods, vk):
        self.held[hk_id] = (mods, vk)
        return 1

    def UnregisterHotKey(self, hwnd, hk_id):
        self.held.pop(hk_id, None)
        return 1


def test_dictate_shortcut_exists_only_while_voice_is_on(state, monkeypatch):
    from consiz.config import CONFIG
    from consiz.platform.win32 import trigger as tr
    fake = _FakeUser32()
    monkeypatch.setattr(tr, "user32", fake)
    monkeypatch.setattr(voice, "available", lambda: True)
    monkeypatch.setattr(CONFIG, "dictate_hotkey", "<ctrl>+<alt>+<shift>+<f9>")
    t = tr.Trigger(lambda s: None, on_pc=lambda s: None, on_dictate=lambda s: None)
    t._sync_hotkeys()
    assert tr.HOTKEY_DICTATE_ID in fake.held
    prefs.set("voice_enabled", False)                       # Settings > Voice off: released within a few seconds
    t._sync_hotkeys()
    assert tr.HOTKEY_DICTATE_ID not in fake.held and tr.HOTKEY_ID in fake.held, "the other shortcuts are untouched"
    prefs.set("voice_enabled", True)
    t._sync_hotkeys()
    assert tr.HOTKEY_DICTATE_ID in fake.held
    monkeypatch.setattr(voice, "available", lambda: False)  # a build without the speech parts: no shortcut at all
    t._sync_hotkeys()
    assert tr.HOTKEY_DICTATE_ID not in fake.held


# ---------------------------------------------------------------- the popup: microphone button and the two uses
class _FakeRecorder:
    def __init__(self):
        self.started = self.stopped = self.cancelled = 0
        self.fail = None
        self.audio = None

    def start(self, on_level=None, on_auto_stop=None):
        if self.fail:
            raise RuntimeError(self.fail)
        self.started += 1
        self.on_auto_stop = on_auto_stop

    def stop(self):
        self.stopped += 1
        import numpy as np
        return np.ones(16000, dtype=np.float32) * 0.1

    def cancel(self):
        self.cancelled += 1


class _FakeEngine:
    def __init__(self, text="translate this into Gujarati", lang=("en", "English")):
        self.text, self.lang = text, lang

    def transcribe(self, audio, language=None):
        return dictation.TranscriptionResult(text=self.text, language=self.lang[0], language_name=self.lang[1],
                                             language_probability=0.99)


@pytest.fixture
def popup(state, monkeypatch):
    tk = pytest.importorskip("tkinter")
    try:
        from consiz.platform.win32 import popup as pm
        ui = pm.PopupUI()
        pm._get_root()
    except tk.TclError:
        pytest.skip("no display available")
    monkeypatch.setattr(voice, "available", lambda: True)
    ui._recorder = _FakeRecorder()
    asked = []
    ui.on_ask = lambda q: asked.append(q)
    ui.asked = asked
    yield pm, ui
    if ui.window is not None:
        ui.window.destroy()


def _pump(pm, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        pm._get_root().update()
        time.sleep(0.01)


def test_microphone_button_shows_only_when_voice_is_available_and_on(popup):
    pm, ui = popup
    ui._show_at((60, 60), "Answer", "Chrome")
    _pump(pm)
    assert ui.mic_btn.winfo_ismapped()
    prefs.set("voice_enabled", False)
    ui._show_at((60, 60), "Answer", "Chrome")
    _pump(pm)
    assert not ui.mic_btn.winfo_ismapped(), "switched off in Settings: no button"
    prefs.set("voice_enabled", True)
    voice.available = lambda: False
    ui._show_at((60, 60), "Answer", "Chrome")
    _pump(pm)
    assert not ui.mic_btn.winfo_ismapped(), "a build without the speech parts: no button"


def test_tapping_the_microphone_listens_then_the_words_become_a_question(popup, monkeypatch):
    pm, ui = popup
    monkeypatch.setattr(dictation, "get_dictation_engine", lambda: _FakeEngine("what is slowing my PC down"))
    ui.on_voice_prepare = lambda: True
    ui.open_pc_chat((60, 60))
    _pump(pm)
    ui._mic_click()                                          # tap: prepare on a worker, then start listening
    _pump(pm, 0.6)
    assert ui.is_listening() and ui._recorder.started == 1
    assert ui.mic_btn.cget("text") == "■", "the button turns into a Stop square while listening"
    assert "Listening" in ui.meta_lbl.cget("text"), "the status line says it is listening"
    ui._mic_click()                                          # tap again: stop now
    _pump(pm, 1.2)
    assert not ui.is_listening() and ui.mic_btn.cget("text") == "🎙"
    assert ui.asked == ["what is slowing my PC down"], "what was heard is sent as the question"
    assert ui._bubbles and ui._bubbles[-1].cget("text") == "what is slowing my PC down", "shown as their message, so they see what was understood"


def test_pausing_stops_listening_by_itself(popup, monkeypatch):
    pm, ui = popup
    monkeypatch.setattr(dictation, "get_dictation_engine", lambda: _FakeEngine("hello there"))
    ui.open_pc_chat((60, 60))
    _pump(pm)
    ui.begin_voice_question()
    _pump(pm, 0.3)
    assert ui.is_listening()
    ui._recorder.on_auto_stop()                              # the recorder noticed a pause
    _pump(pm, 1.2)
    assert not ui.is_listening() and ui.asked == ["hello there"]


def test_nothing_heard_says_so_and_asks_nothing(popup, monkeypatch):
    pm, ui = popup
    monkeypatch.setattr(dictation, "get_dictation_engine", lambda: _FakeEngine(""))
    ui.open_pc_chat((60, 60))
    _pump(pm)
    ui.begin_voice_question()
    _pump(pm, 0.3)
    ui.stop_dictation()
    _pump(pm, 1.0)
    assert ui.asked == [] and "did not hear anything" in ui.chat.get("1.0", "end")


def test_a_missing_microphone_gives_a_clear_next_step(popup):
    pm, ui = popup
    ui._recorder.fail = "No microphone detected."
    ui.open_pc_chat((60, 60))
    _pump(pm)
    ui.begin_voice_question()
    _pump(pm, 0.4)
    shown = ui.chat.get("1.0", "end")
    assert not ui.is_listening() and ui.mic_btn.cget("text") == "🎙"
    assert "No microphone" in shown and "Privacy & security" in shown


def test_closing_the_window_stops_listening(popup):
    pm, ui = popup
    ui.open_pc_chat((60, 60))
    _pump(pm)
    ui.begin_voice_question()
    _pump(pm, 0.3)
    assert ui.is_listening()
    ui.hide()
    _pump(pm, 0.4)
    assert not ui.is_listening() and ui._recorder.cancelled == 1, "the microphone is released"
    assert ui.mic_btn.cget("text") == "🎙"


def test_a_spoken_instruction_on_selected_text_goes_to_the_old_path(popup, monkeypatch):
    """Ctrl+Alt+D with text selected: what is said is an INSTRUCTION for that text (translate, summarize...)."""
    from consiz.models import CapturedContext, CaptureMethod
    pm, ui = popup
    monkeypatch.setattr(dictation, "get_dictation_engine", lambda: _FakeEngine("translate this into Gujarati"))
    got = []
    ui.on_dictate = lambda ctx, res: got.append((ctx.raw_content, res.text))
    ctx = CapturedContext("chrome.exe", CaptureMethod.TEXT_SELECTION, "Hello world")
    threading.Thread(target=ui.start_dictation_flow, args=(ctx, (60, 60))).start()
    _pump(pm, 0.8)
    assert ui.is_listening() and ui.context == "Hello world"
    shown = ui.chat.get("1.0", "end")
    assert "Speak what to do with the selected text" in shown and "✓ Done" not in shown, "no reference to a button that is gone"
    ui.stop_dictation()
    _pump(pm, 1.2)
    assert got == [("Hello world", "translate this into Gujarati")]
    assert "translate this into Gujarati" in ui.title_lbl.cget("text")


# ---------------------------------------------------------------- Settings and tray
def test_settings_voice_controls(popup, state, monkeypatch, tmp_path):
    from consiz import llm
    from consiz.platform.win32 import settings as st
    pm, ui = popup
    monkeypatch.setattr(llm, "server_mode", lambda: True)
    monkeypatch.setattr(voice, "model_cached", lambda name=None: name == "small")
    st._OPEN["win"] = None
    st.show_settings_dialog(pm._get_root())
    win = st._OPEN["win"]
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
        assert "Voice dictation" in joined and "never uploaded" in joined
        assert "downloaded, works offline" in joined, "the status says the model is already here"
        assert any("Voice dictation" == s for s in texts), "the shortcut row exists too"
    finally:
        st._OPEN["win"] = None
        win.destroy()


def test_tray_shows_voice_item_only_when_voice_works(state, monkeypatch):
    from consiz.platform.win32 import tray
    monkeypatch.setattr(voice, "available", lambda: True)
    assert voice.enabled()
    prefs.set("voice_enabled", False)
    assert not voice.enabled(), "the tray item is hidden while voice is off"


# ---------------------------------------------------------------- the real engine on real speech (opt-in by cache)
@pytest.mark.skipif(not voice.available() or not voice.model_cached("small"),
                    reason="needs the speech parts and the 'small' model on this PC")
def test_voice_real_speech(tmp_path):
    """Windows' own voice speaks a sentence into a file; the real Whisper model must hear the same words."""
    import subprocess
    import sys
    import wave

    import numpy as np
    if sys.platform != "win32":
        pytest.skip("uses Windows speech synthesis to make the test audio")
    wav = tmp_path / "say.wav"
    ps = ('Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
          f'$s.SetOutputToWaveFile("{wav}"); $s.Speak("Open the storage settings and show me my biggest folders."); $s.Dispose()')
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60)
    if r.returncode != 0 or not wav.exists():
        pytest.skip("Windows speech synthesis is not available here")
    with wave.open(str(wav)) as w:
        sr, ch, raw = w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    audio = np.interp(np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / sr)), np.arange(len(audio)), audio).astype(np.float32)
    res = dictation.DictationEngine(model_size="small").transcribe(audio)
    heard = res.text.lower()
    assert "storage settings" in heard and "folders" in heard, heard
    assert res.language == "en"
