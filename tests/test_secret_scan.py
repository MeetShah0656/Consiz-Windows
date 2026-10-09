"""The secret scanner finds the kinds of secrets this project uses, and the repository itself is clean."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("secret_scan", ROOT / "scripts" / "secret_scan.py")
secret_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(secret_scan)


def test_it_recognises_the_secrets_this_project_handles():
    fake = {
        "OpenRouter key": "sk-or-v1-" + "a1b2c3d4" * 4,
        "Google client secret": "GOCSPX-" + "Ab1_Cd2-Ef3" * 3,
        "GitHub token": "ghp_" + "A1b2C3d4E5" * 4,
        "Private key": "-----BEGIN RSA PRIVATE KEY-----",
        "Neon/Postgres URL with password": "postgresql://user:hunter2abc@ep-1.neon.tech/db",
    }
    for label, sample in fake.items():
        assert label in secret_scan.find_secrets(f"x = '{sample}'"), label


def test_ordinary_text_and_placeholders_are_not_flagged():
    for text in ("OPENROUTER_API_KEY=paste-your-key-here", "postgresql://user@host/db", "sk-or-v1-", "just words"):
        assert secret_scan.find_secrets(text) == [], text


def test_the_repository_has_no_secrets_in_tracked_files():
    problems, files = secret_scan.scan(ROOT)
    assert files > 50, "git ls-files returned almost nothing: is this a git checkout?"
    assert problems == [], problems
