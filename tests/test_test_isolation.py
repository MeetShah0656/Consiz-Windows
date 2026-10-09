"""Tests must never touch the developer's real Consiz (settings, sign-in, log): a past test signed the developer out for real."""
import pathlib

from consiz import auth, logs, prefs


def test_the_sign_in_store_settings_and_log_are_private_to_each_test():
    real = pathlib.Path.home() / ".consiz"
    for path in (auth.SESSION_FILE, prefs.STORE, logs.LOG_FILE):
        assert real not in pathlib.Path(path).parents, f"{path} is inside the real ~/.consiz"


def test_signing_in_and_out_in_a_test_never_reaches_the_windows_credential_manager():
    import keyring
    before = keyring.get_password(auth.KEYRING_SERVICE, auth.KEYRING_USER)
    auth._save({"email": "test@example.com"}, "fake-refresh-token")
    assert auth.signed_in() and auth._kr_get() == "fake-refresh-token"
    assert keyring.get_password(auth.KEYRING_SERVICE, auth.KEYRING_USER) == before, "the real credential was touched"
    auth.sign_out()
    assert not auth.signed_in()
    assert keyring.get_password(auth.KEYRING_SERVICE, auth.KEYRING_USER) == before, "the real credential was touched"
