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
    pc_mode._read_cache.clear()
    yield
    pc_mode._allowed.clear()
    pc_mode._read_cache.clear()


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
    block, _imgs, declined = pc_mode.gather_contents([1], WINS, read_text, confirm, lambda m: None)
    assert not declined and reads == [101] and asked == [["excel.exe: Report.xlsx - Excel"]]
    assert "hunter22secret" not in block and "REDACTED" in block
    assert len(block) <= pc_mode.MAX_PER_WINDOW + 200
    pc_mode.gather_contents([1], WINS, read_text, confirm, lambda m: None)   # same window again: no new prompt
    assert len(asked) == 1


def test_gather_declined_reads_nothing():
    reads = []
    block, _imgs, declined = pc_mode.gather_contents([1], WINS, lambda h: reads.append(h) or ("t", "tree"),
                                              lambda t: False, lambda m: None)
    assert declined and block == "" and reads == []


def test_gather_blocks_sensitive_and_never_asks_for_them():
    asked, reads = [], []
    block, _imgs, declined = pc_mode.gather_contents([3, 4], WINS, lambda h: reads.append(h) or ("secret", "tree"),
                                              lambda t: asked.append(t) or True, lambda m: None)
    assert not declined and reads == [] and asked == [] and block.count("NOT READ") == 2


def test_browser_page_hidden_gives_the_accessibility_hint():
    block, _imgs, _ = pc_mode.gather_contents([2], WINS, lambda h: ("Inbox", "tree"), lambda t: True, lambda m: None)
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


# ------------------------------------------------------------------ pictures for apps that hide their text
def test_thin_text_falls_back_to_a_picture_of_that_window():
    shots, notes = [], []
    block, images, declined = pc_mode.gather_contents(
        [2], WINS, lambda h: ("Inbox", "tree"), lambda t: True, notes.append,
        capture_image=lambda h: shots.append(h) or "QUJD")
    assert not declined and shots == [102] and images == ["QUJD"]
    assert "PICTURE of the window" in block and "image 1" in block and any("picture" in n.lower() for n in notes)


def test_enough_text_means_no_picture():
    block, images, _ = pc_mode.gather_contents([1], WINS, lambda h: ("x" * 600, "tree"), lambda t: True,
                                               lambda m: None, capture_image=lambda h: pytest.fail("no picture needed"))
    assert images == [] and "xxxx" in block


def test_pictures_are_capped_and_a_failed_capture_falls_back_to_text_hint():
    wins = [dict(WINS[1], hwnd=200 + i, title=f"Tab {i}") for i in range(4)]
    _b, images, _ = pc_mode.gather_contents([1, 2, 3], wins, lambda h: ("", "none"), lambda t: True,
                                            lambda m: None, capture_image=lambda h: "AAAA")
    assert len(images) == pc_mode.MAX_IMAGES
    pc_mode._allowed.clear()
    pc_mode._read_cache.clear()
    block, images, _ = pc_mode.gather_contents([1], wins, lambda h: ("", "none"), lambda t: True,
                                               lambda m: None, capture_image=lambda h: None)
    assert images == [] and "chrome://accessibility" in block


def test_sensitive_windows_never_get_a_picture_either():
    shots = []
    pc_mode.gather_contents([3, 4], WINS, lambda h: ("", "none"), lambda t: True, lambda m: None,
                            capture_image=lambda h: shots.append(h) or "AAAA")
    assert shots == []


def test_read_round_trip_attaches_the_picture_to_the_second_call():
    seen = []
    fn = _stream_fn(["READ: 2\n", "- The page says Raise your team rate limit.\n"], seen)
    out = "".join(pc_mode.stream_answer("what does the page say?", [], "SNAP", WINS, stream_fn=fn,
                                       read_text=lambda h: ("", "none"), confirm=lambda t: True,
                                       notify=lambda m: None, capture_image=lambda h: "QUJD"))
    assert "rate limit" in out
    last = seen[1][-1]["content"]
    assert isinstance(last, list) and last[0]["type"] == "text" and last[1]["image_url"]["url"].endswith("QUJD")
    assert llm.has_images(seen[1]) and not llm.has_images(seen[0])


def test_vision_requests_use_the_image_reading_models(monkeypatch):
    sent = {}

    class R:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self):
            return iter([b"data: [DONE]"])

    monkeypatch.setattr(llm, "_server_url", lambda: "")
    monkeypatch.setattr(llm, "_api_key", lambda: "k")
    monkeypatch.setattr(llm.requests, "post", lambda url, json=None, **kw: sent.update(body=json) or R())
    with_pic = llm.pc_messages("S", [], "q", contents="C", images=["QUJD"])
    list(llm._openrouter_sse(with_pic, llm._REASONING_OFF, 50))
    assert sent["body"]["model"] == llm.CONFIG.vision_model and "gemma" in sent["body"]["model"]
    list(llm._openrouter_sse(llm.pc_messages("S", [], "q"), llm._REASONING_OFF, 50))
    assert sent["body"]["model"] == llm.CONFIG.openrouter_model


def test_capture_helper_returns_a_real_jpeg_of_a_window():
    import base64
    import ctypes
    import sys
    import tkinter as tk
    if sys.platform != "win32":
        pytest.skip("Windows capture")
    from consiz.platform.win32 import readwin
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    try:
        root.geometry("420x300+120+120")
        tk.Label(root, text="Consiz capture test " * 6, wraplength=380, bg="white", fg="black").pack(expand=True, fill="both")
        root.update()
        root.after(200, root.quit)
        root.mainloop()                                   # let it paint once
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        pic = readwin.capture_window_jpeg_b64(hwnd)
    finally:
        root.destroy()
    assert pic, "our own visible window must be capturable"
    raw = base64.b64decode(pic)
    assert raw[:3] == bytes([0xFF, 0xD8, 0xFF]) and len(raw) < 1_400_000     # JPEG magic number



# ------------------------------------------------------------------ production fixes: leak, minimized, cache, draft
def test_internal_read_line_is_never_shown_to_the_user():
    seen = []
    fn = _stream_fn(["- Exa page, window 4.\n- Window 4 is minimized, use READ: 4 to see inside\n- Spent 18 dollars.\n"], seen)
    out = "".join(pc_mode.stream_answer("what is on the exa page?", [], "SNAP", WINS, stream_fn=fn,
                                       read_text=lambda h: ("", "none"), confirm=lambda t: True,
                                       notify=lambda m: None))
    assert "READ" not in out and "Spent 18 dollars" in out and "Exa page" in out


def test_minimized_window_is_not_photographed_and_gets_a_switch_hint():
    shots = []
    wins = [dict(WINS[1], minimized=True)]
    block, images, _ = pc_mode.gather_contents([1], wins, lambda h: ("", "none"), lambda t: True,
                                               lambda m: None, capture_image=lambda h: shots.append(h) or "AAAA")
    assert shots == [] and images == [] and "MINIMIZED" in block and "ACTION: focus_window 1" in block


def test_second_question_about_the_same_window_reuses_the_read():
    reads, shots = [], []
    read = lambda h: reads.append(h) or ("Total 5000 " + "x" * 400, "tree")        # noqa: E731
    pc_mode.gather_contents([1], WINS, read, lambda t: True, lambda m: None)
    block, _i, _d = pc_mode.gather_contents([1], WINS, read, lambda t: pytest.fail("no second prompt"),
                                            lambda m: None)
    assert reads == [101] and "Total 5000" in block                              # read once, used twice
    wins = [dict(WINS[1])]
    cap = lambda h: shots.append(h) or "PIC"                                     # noqa: E731
    pc_mode.gather_contents([1], wins, lambda h: ("", "none"), lambda t: True, lambda m: None, capture_image=cap)
    _b, images, _d = pc_mode.gather_contents([1], wins, lambda h: ("", "none"), lambda t: True,
                                             lambda m: None, capture_image=cap)
    assert shots == [102] and images == ["PIC"]                                  # photographed once, reused


def test_prompt_handles_tell_someone_requests():
    first = llm.pc_messages("S", [], "q")[0]["content"]
    assert "Draft:" in first and "tell Hitarth" in first and "cannot send it" in first
