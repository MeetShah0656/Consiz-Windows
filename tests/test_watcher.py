"""The opt-in PC watcher (T-12): off by default, quiet unless something stays bad, one message then a long pause, never
sends or changes anything. The clock, the readings and the message box are all fake."""
import sys

import pytest

from consiz import watcher


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def make(readings, enabled=True):
    """A watcher fed from a list of readings (the last one repeats); returns (watcher, shown messages, clock)."""
    shown, clock, calls = [], Clock(), {"n": 0}

    def sampler():
        calls["n"] += 1
        return readings[min(calls["n"] - 1, len(readings) - 1)]

    w = watcher.Watcher(sampler, lambda title, text: shown.append((title, text)), enabled=lambda: enabled,
                        hint=lambda: "Ctrl+Alt+A", clock=clock)
    w.calls, w.clock = calls, clock
    return w, shown


BUSY = {"cpu": 95.0, "ram": 40.0, "top": [("chrome.exe", 70.0), ("code.exe", 12.0)], "disk_free_percent": 40.0}
CALM = {"cpu": 10.0, "ram": 40.0, "top": [], "disk_free_percent": 40.0}


def test_it_does_nothing_while_it_is_switched_off():
    w, shown = make([BUSY], enabled=False)
    for _ in range(20):
        assert w.tick() == []
    assert shown == [] and w.calls["n"] == 0, "it must not even read the PC while off"


def test_a_busy_minute_is_not_worth_a_message_but_three_minutes_is():
    w, shown = make([BUSY])
    for _ in range(watcher.CPU_TICKS - 1):
        assert w.tick() == []
    assert w.tick() == ["cpu"] and len(shown) == 1
    title, text = shown[0]
    assert "slow" in title.lower() and "chrome.exe (70%)" in text and "Ctrl+Alt+A" in text and "3 minutes" in text


def test_a_short_spike_resets_the_count():
    w, shown = make([BUSY] * (watcher.CPU_TICKS - 1) + [CALM] + [BUSY] * (watcher.CPU_TICKS - 1))
    for _ in range(2 * watcher.CPU_TICKS - 1):
        w.tick()
    assert shown == []


def test_one_message_then_quiet_for_half_an_hour():
    w, shown = make([BUSY])
    for _ in range(watcher.CPU_TICKS):
        w.tick()
    assert len(shown) == 1
    for _ in range(50):                                      # still busy for 25 more minutes
        w.clock.now += watcher.INTERVAL_S
        w.tick()
    assert len(shown) == 1
    w.clock.now += 30 * 60
    w.tick()
    assert len(shown) == 2, "after the pause it may speak again"


def test_memory_and_disk_have_their_own_rules():
    w, shown = make([{"cpu": 5.0, "ram": 95.0, "top": [("chrome.exe", 3.0)], "disk_free_percent": 40.0}])
    for _ in range(watcher.RAM_TICKS):
        w.tick()
    assert [t for t, _ in shown] == ["Memory is almost full"]
    w2, shown2 = make([{"cpu": 5.0, "ram": 30.0, "top": [], "disk_free_percent": 3.0, "disk_free_gb": 9.5, "disk_drive": "C:"}])
    assert w2.tick() == ["disk"] and "9.5 GB free" in shown2[0][1]
    w2.clock.now += 3600
    assert w2.tick() == [], "a full disk is mentioned once a day, not every hour"
    w2.clock.now += 24 * 3600
    assert w2.tick() == ["disk"]


def test_a_failed_reading_or_message_never_breaks_it():
    shown = []
    broken = watcher.Watcher(lambda: 1 / 0, lambda t, x: shown.append(t), enabled=lambda: True)
    assert broken.tick() == []
    w = watcher.Watcher(lambda: BUSY, lambda t, x: (_ for _ in ()).throw(RuntimeError("no tray")), enabled=lambda: True)
    for _ in range(watcher.CPU_TICKS):
        w.tick()                                             # the notifier fails: no exception escapes


def test_turning_it_off_forgets_the_count():
    flag = {"on": True}
    shown = []
    w = watcher.Watcher(lambda: BUSY, lambda t, x: shown.append(t), enabled=lambda: flag["on"], clock=Clock())
    for _ in range(watcher.CPU_TICKS - 1):
        w.tick()
    flag["on"] = False
    w.tick()
    flag["on"] = True
    w.tick()
    assert shown == [], "five busy checks, then off, then one more must not add up to a message"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_the_real_reading_returns_sane_numbers():
    from consiz.platform.win32 import sysinfo
    sysinfo.quick_sample()                                   # the first call only primes the per-program counters
    s = sysinfo.quick_sample()
    assert 0 <= s["cpu"] <= 100 and 0 <= s["ram"] <= 100
    assert 0 <= s["disk_free_percent"] <= 100 and s["disk_drive"].endswith(":")
    assert all(isinstance(name, str) and pct >= 0 for name, pct in s["top"])


def test_it_is_off_by_default_and_the_setting_is_listed():
    from consiz import prefs
    assert prefs.get("watcher_enabled", False) is False
