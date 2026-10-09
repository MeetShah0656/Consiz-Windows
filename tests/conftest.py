"""No test may read or write the real settings file (~/.consiz/prefs.json): a size the developer dragged the answer window
to once made the layout tests fail, and a test that saved a size overwrote it. Every test gets an empty, private one."""
import pytest

from consiz import prefs


@pytest.fixture(autouse=True)
def _private_prefs(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "STORE", tmp_path / "isolated_prefs.json")
