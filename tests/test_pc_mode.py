"""Ask-about-my-PC mode: what the model is shown (computed highlights, redaction, size cap) and the real snapshot."""
import sys
import time

import pytest

from consiz import llm, pc_mode


def _snap(**over):
    snap = {
        "taken_at": "2026-10-07 12:00",
        "system": {"cpu_percent": 20.0, "cpu_cores": 8, "ram_total_gb": 16.0, "ram_used_gb": 14.0, "ram_percent": 87.5,
                   "uptime_hours": 200.0, "process_count": 300,
                   "disks": [{"drive": "C:\\", "total_gb": 475.0, "free_gb": 1.3, "percent_used": 99.7}],
                   "battery": {"percent": 15, "plugged": False}},
        "apps": [{"name": "brave.exe", "processes": 36, "ram_mb": 4800, "cpu_percent": 8.0},
                 {"name": "chrome.exe", "processes": 20, "ram_mb": 2500, "cpu_percent": 1.0},
                 {"name": "code.exe", "processes": 5, "ram_mb": 900, "cpu_percent": 0.1}],
        "windows": [{"title": "YouTube - Brave", "app": "brave.exe", "foreground": True, "minimized": False},
                    {"title": "Report.xlsx - Excel", "app": "excel.exe", "foreground": False, "minimized": True}],
        "startup": ["OneDrive", "Spotify"],
        "network": {"established": 40, "by_app": [{"app": "brave.exe", "connections": 18}]},
    }
    snap.update(over)
    return snap


def test_highlights_are_computed_by_code():
    text = " ".join(pc_mode.highlights(_snap()))
    assert "99.7% full" in text and "1.3 GB free" in text
    assert "Memory is 87.5%" in text and "8 days" in text and "Battery is low" in text
    assert "brave.exe, chrome.exe, code.exe" in text and "8.0 GB" in text and "57%" in text   # 8200 MB of 14336 MB used


def test_render_lists_windows_programs_and_flags():
    text, summary = pc_mode.render(_snap())
    assert "[FOCUSED]" in text and "[minimized]" in text and "brave.exe: 36 process(es)" in text
    assert "[S1] OneDrive, [S2] Spotify" in text and "HIGHLIGHTS" in text
    assert summary == "2 windows · 3 programs"


def test_secrets_in_window_titles_are_redacted():
    snap = _snap(windows=[{"title": "notes - password: hunter22secret", "app": "notepad.exe",
                           "foreground": True, "minimized": False}])
    text, _ = pc_mode.render(snap)
    assert "hunter22secret" not in text and "REDACTED" in text


def test_snapshot_text_is_capped():
    many = [{"title": "x" * 140, "app": "a.exe", "foreground": False, "minimized": False}] * 500
    text, _ = pc_mode.render(_snap(windows=many, startup=["s" * 100] * 200))
    assert len(text) <= pc_mode.MAX_CHARS + 50


def test_snapshot_is_reused_briefly(monkeypatch):
    monkeypatch.setitem(pc_mode._cache, "at", 0.0)
    monkeypatch.setitem(pc_mode._cache, "text", "")
    calls = []
    collect = lambda: calls.append(1) or _snap()          # noqa: E731
    pc_mode.get_context(collect=collect)
    pc_mode.get_context(collect=collect)
    assert len(calls) == 1
    pc_mode.get_context(collect=collect, force=True)
    assert len(calls) == 2


def test_pc_messages_shape_and_rules():
    msgs = llm.pc_messages("SNAP", [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}],
                           "why slow?")
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert "<pc_snapshot>\nSNAP\n</pc_snapshot>" in msgs[-1]["content"] and msgs[-1]["content"].endswith("why slow?")
    assert "never calculate" in msgs[0]["content"].lower() and "malware" in msgs[0]["content"]
    assert "SNAP" not in msgs[1]["content"]                # old turns do not carry the old snapshot


@pytest.mark.skipif(sys.platform != "win32", reason="Windows collector")
def test_real_snapshot_has_the_contract_fields():
    from consiz.platform.win32 import sysinfo
    t = time.time()
    snap = sysinfo.snapshot()
    assert time.time() - t < 15
    assert {"taken_at", "system", "apps", "windows", "startup", "network"} <= set(snap)
    assert snap["system"]["process_count"] > 10 and snap["apps"][0]["ram_mb"] >= snap["apps"][-1]["ram_mb"]
    assert all({"title", "app", "foreground", "minimized"} <= set(w) for w in snap["windows"])
    assert all(a["name"] != "System Idle Process" for a in snap["apps"])
    text, _ = pc_mode.render(snap)
    assert "SYSTEM" in text
