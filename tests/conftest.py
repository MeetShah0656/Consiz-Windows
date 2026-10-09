"""No test may touch the developer's real Consiz: not the settings file (~/.consiz/prefs.json), not the saved Google sign-in
(session file + Windows Credential Manager), not the log. Every test gets empty private copies.

Why this exists: a size the developer dragged the answer window to made a layout test fail; and a test of "Clear local data"
once SIGNED THE DEVELOPER OUT FOR REAL and emptied their log, because it called the real sign-out. Never again: the
sign-in store is replaced by an in-memory fake for every test, whatever the test does.
"""
import pytest

from consiz import auth, logs, prefs


@pytest.fixture(autouse=True)
def _private_state(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "STORE", tmp_path / "isolated_prefs.json")
    monkeypatch.setattr(logs, "LOG_FILE", tmp_path / "isolated.log")
    monkeypatch.setattr(auth, "SESSION_FILE", tmp_path / "isolated_session.json")
    vault = {"token": ""}                                              # stands in for the Windows Credential Manager
    monkeypatch.setattr(auth, "_kr_get", lambda: vault["token"])
    monkeypatch.setattr(auth, "_kr_set", lambda token: vault.update(token=token) or True)
    monkeypatch.setattr(auth, "_kr_delete", lambda: vault.update(token=""))
    monkeypatch.setitem(auth._ID, "token", "")
    monkeypatch.setitem(auth._ID, "exp", 0.0)
