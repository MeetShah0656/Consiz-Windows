"""The first question after startup must not wait for a Google token refresh (it cost 2.6 s)."""
import time

import pytest

from consiz import auth


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    auth._ID["token"], auth._ID["exp"] = "", 0.0
    monkeypatch.setattr(auth, "_refresh_token", lambda: "refresh-abc")
    monkeypatch.setattr(auth, "enabled", lambda: True)
    monkeypatch.setattr(auth, "signed_in", lambda: True)
    yield
    auth._ID["token"], auth._ID["exp"] = "", 0.0


def test_startup_check_keeps_the_fresh_token_for_the_first_question(monkeypatch):
    calls = []
    monkeypatch.setattr(auth, "_token_request",
                        lambda data: calls.append(data) or {"id_token": "ID1", "expires_in": 3600})
    assert auth.revalidate() is True and len(calls) == 1
    monkeypatch.setattr(auth, "_token_request", lambda data: pytest.fail("the first question must not refresh again"))
    assert auth.id_token() == "ID1"


def test_token_is_refreshed_early_not_during_a_question(monkeypatch):
    auth._ID["token"], auth._ID["exp"] = "OLD", time.time() + 200          # < 5 minutes left
    monkeypatch.setattr(auth, "_token_request", lambda data: {"id_token": "NEW", "expires_in": 3600})
    assert auth.id_token() == "NEW"
    auth._ID["token"], auth._ID["exp"] = "OK", time.time() + 1800          # 30 minutes left: reuse
    monkeypatch.setattr(auth, "_token_request", lambda data: pytest.fail("no refresh needed"))
    assert auth.id_token() == "OK"


def test_rejected_startup_check_signs_out_and_caches_nothing(monkeypatch):
    def reject(data):
        err = auth.AuthError("revoked")
        err.rejected = True
        raise err

    out = []
    monkeypatch.setattr(auth, "_token_request", reject)
    monkeypatch.setattr(auth, "sign_out", lambda: out.append(1))
    assert auth.revalidate() is False and out == [1] and auth._ID["token"] == ""


def test_ai_calls_share_one_kept_alive_connection():
    from consiz import llm
    import requests
    assert isinstance(llm._SESSION, requests.Session)
    assert llm._SESSION.get_adapter("https://consiz-windows.onrender.com")._pool_maxsize >= 2
    assert llm.KEEPALIVE_SECONDS < 15 * 60                                 # shorter than the host's idle-sleep time
