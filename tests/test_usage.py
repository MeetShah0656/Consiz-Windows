"""Tests for consiz/usage.py quota tracking."""
import pytest
from consiz import usage


def test_bar_rendering():
    assert usage.bar(100, width=10) == "██████████"
    assert usage.bar(0, width=10) == "░░░░░░░░░░"
    assert usage.bar(50, width=10) == "█████░░░░░"


def test_quota_limits():
    assert usage.limit_for(has_credits=False) == 50
    assert usage.limit_for(has_credits=True) == 1000


def test_snapshot_and_record(monkeypatch, tmp_path):
    # Route usage file to temporary path
    test_store = tmp_path / "test_usage.json"
    monkeypatch.setattr(usage, "STORE", test_store)

    keys = ["sk-or-v1-abc12345678"]
    snap = usage.snapshot(keys, has_credits=False)
    assert snap["total"] == 50
    assert snap["used"] == 0
    assert snap["left"] == 50
    assert snap["pct_left"] == 100

    usage.record(keys[0])
    snap2 = usage.snapshot(keys, has_credits=False)
    assert snap2["used"] == 1
    assert snap2["left"] == 49

    # Test exhausted flag
    usage.record(keys[0], exhausted=True)
    snap3 = usage.snapshot(keys, has_credits=False)
    assert snap3["used"] == 50
    assert snap3["left"] == 0
    assert snap3["pct_left"] == 0

    c = usage.compact(keys, has_credits=False)
    assert "quota used up" in c
