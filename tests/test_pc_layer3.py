"""PC mode, layer 3 (read inside windows) and one-click actions: permission, safety limits, protocol."""
import pytest

from consiz import llm, pc_actions, pc_mode

WINS = [
    {"title": "Report.xlsx - Excel", "app": "excel.exe", "foreground": True, "minimized": False, "hwnd": 101},
    {"title": "Inbox - Gmail - Google Chrome", "app": "chrome.exe", "foreground": False, "minimized": False, "hwnd": 102},
    {"title": "KeePass Database", "app": "keepass.exe", "foreground": False, "minimized": False, "hwnd": 103},
    {"title": "My bank - Brave (Private browsing)", "app": "brave.exe", "foreground": False, "minimized": False,
     "hwnd": 104},
]


@pytest.fixture(autouse=True)
def fresh_session():
    pc_mode._allowed.clear()
    yield
    pc_mode._allowed.clear()


# ------------------------------------------------------------------ READ protocol + blocklist
def test_parse_read():
    assert pc_mode.parse_read("READ: 2, 1", 4) == [2, 1]
    assert pc_mode.parse_read("**READ:** 3", 4) == [3] or pc_mode.parse_read("READ: 3", 4) == [3]
    assert pc_mode.parse_read("READ: 9, 0, 2, 2", 4) == [2]                 # out of range / duplicates dropped
    assert pc_mode.parse_read("READ: 1,2,3,4", 4) == [1, 2, 3]              # at most 3 windows
    assert pc_mode.parse_read("- Disk is full", 4) == []


def test_sensitive_windows_are_never_read():
    assert pc_mode.sensitive_reason(WINS[2]) and pc_mode.sensitive_reason(WINS[3])
    assert pc_mode.sensitive_reason(WINS[0]) is None and pc_mode.sensitive_reason(WINS[1]) is None


def test_gather_asks_once_redacts_and_caps():
    asked, reads = [], []

    def read_text(hwnd):
        reads.append(hwnd)
        return "Total 5000 password: hunter22secret " + "x" * 20000, "tree"

    confirm = lambda titles: asked.append(titles) or True            # noqa: E731
    block, declined = pc_mode.gather_contents([1], WINS, read_text, confirm, lambda m: None)
    assert not declined and reads == [101] and asked == [["excel.exe: Report.xlsx - Excel"]]
    assert "hunter22secret" not in block and "REDACTED" in block
    assert len(block) <= pc_mode.MAX_PER_WINDOW + 200
    pc_mode.gather_contents([1], WINS, read_text, confirm, lambda m: None)   # same window again: no new prompt
    assert len(asked) == 1


def test_gather_declined_reads_nothing():
    reads = []
    block, declined = pc_mode.gather_contents([1], WINS, lambda h: reads.append(h) or ("t", "tree"),
                                              lambda t: False, lambda m: None)
    assert declined and block == "" and reads == []


def test_gather_blocks_sensitive_and_never_asks_for_them():
    asked, reads = [], []
    block, declined = pc_mode.gather_contents([3, 4], WINS, lambda h: reads.append(h) or ("secret", "tree"),
                                              lambda t: asked.append(t) or True, lambda m: None)
    assert not declined and reads == [] and asked == [] and block.count("NOT READ") == 2


def test_browser_page_hidden_gives_the_accessibility_hint():
    block, _ = pc_mode.gather_contents([2], WINS, lambda h: ("Inbox", "tree"), lambda t: True, lambda m: None)
    assert "chrome://accessibility" in block and "Native accessibility API support" in block


# ------------------------------------------------------------------ the two-step answer
def _stream_fn(replies, seen):
    def fn(messages):
        seen.append(messages)
        text = replies[len(seen) - 1]
        return iter([text[i:i + 7] for i in range(0, len(text), 7)])   # arrives in small pieces
    return fn


def test_plain_answer_streams_through_without_reading():
    seen = []
    out = "".join(pc_mode.stream_answer("why slow?", [], "SNAP", WINS, stream_fn=_stream_fn(["- Disk is full.\n- Free space.\n"], seen),
                                       read_text=lambda h: pytest.fail("must not read"),
                                       confirm=lambda t: pytest.fail("must not ask"), notify=lambda m: None))
    assert out == "- Disk is full.\n- Free space.\n" and len(seen) == 1


def test_read_round_trip():
    seen, notes = [], []
    fn = _stream_fn(["READ: 1\n", "- Total is 5000.\nREAD: 1\n- It is in cell B4.\n"], seen)
    out = "".join(pc_mode.stream_answer("what is the total?", [], "SNAP", WINS, stream_fn=fn,
                                       read_text=lambda h: ("Total 5000", "tree"), confirm=lambda t: True,
                                       notify=notes.append))
    assert out == "- Total is 5000.\n- It is in cell B4.\n"            # stray second READ line removed
    assert len(seen) == 2 and "<window_contents>" in seen[1][-1]["content"] and "Total 5000" in seen[1][-1]["content"]
    assert "READ: <numbers>" not in seen[1][0]["content"] and notes and "Report.xlsx" in notes[0]


def test_declined_read_gives_an_honest_line():
    seen = []
    out = "".join(pc_mode.stream_answer("what is the total?", [], "SNAP", WINS,
                                       stream_fn=_stream_fn(["READ: 1\n"], seen), read_text=lambda h: ("x", "t"),
                                       confirm=lambda t: False, notify=lambda m: None))
    assert "chose not to" in out and len(seen) == 1


def test_read_prompt_rules():
    first = llm.pc_messages("S", [], "q")[0]["content"]
    second = llm.pc_messages("S", [], "q", contents="C")[0]["content"]
    assert "READ: <numbers>" in first and "Do NOT reply with READ" in second and "READ: <numbers>" not in second
    assert "ACTION:" in first and "open_settings <storage" in first


# ------------------------------------------------------------------ one-click actions
def test_action_whitelist():
    a = pc_actions.parse("ACTION: open_settings storage", WINS)
    assert a.kind == "launch" and a.target == "ms-settings:storagesense" and "Storage" in a.label
    assert pc_actions.parse("ACTION: open_task_manager", WINS).target == "taskmgr.exe"
    f = pc_actions.parse("ACTION: focus_window 2", WINS)
    assert f.kind == "focus" and f.target == "102"


@pytest.mark.parametrize("line", [
    "ACTION: delete_file C:\\Users\\x", "ACTION: end_process chrome.exe", "ACTION: open_settings ../../evil",
    "ACTION: open_task_manager now", "ACTION: focus_window 99", "ACTION: focus_window abc", "ACTION:",
    "- not an action", "ACTION: powershell -c calc"])
def test_anything_off_the_list_is_dropped(line):
    assert pc_actions.parse(line, WINS) is None


def test_run_only_calls_the_platform_launcher(monkeypatch):
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows executor")
    from consiz.platform.win32 import actions
    calls = []
    monkeypatch.setattr(actions, "launch", lambda t: calls.append(("launch", t)) or (True, "Opened."))
    monkeypatch.setattr(actions, "focus", lambda h: calls.append(("focus", h)) or (True, "Switched."))
    assert pc_actions.run(pc_actions.parse("ACTION: open_settings storage", WINS)) == (True, "Opened.")
    assert pc_actions.run(pc_actions.parse("ACTION: focus_window 1", WINS)) == (True, "Switched.")
    assert calls == [("launch", "ms-settings:storagesense"), ("focus", 101)]
