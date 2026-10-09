"""Opt-in PC watcher (T-12): tells the person, once, when the PC has been slow, full or short of disk for a few minutes.

Private and cheap on purpose:
  - OFF until the person turns it on in Settings.
  - Every 30 seconds it reads three numbers on THIS PC (CPU, memory, free disk). Nothing is sent anywhere, no AI is called,
    nothing is stored, and it never closes or changes anything: it only shows a message and points to Ask about my PC.
  - One message per problem, then quiet for 30 minutes (a full disk: a day).
The sampler and the notifier are injected, so the rules are tested without waiting or touching Windows.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

INTERVAL_S = 30
CPU_PERCENT, CPU_TICKS = 85.0, 6              # 6 samples = 3 minutes
RAM_PERCENT, RAM_TICKS = 92.0, 4              # 2 minutes
DISK_FREE_PERCENT = 5.0
COOLDOWN_S = {"cpu": 30 * 60, "ram": 30 * 60, "disk": 24 * 3600}


class Watcher:
    def __init__(self, sampler: Callable[[], dict], notify: Callable[[str, str], None],
                 enabled: Callable[[], bool], hint: Callable[[], str] = lambda: "Ctrl+Alt+A",
                 clock: Callable[[], float] = time.time):
        self._sample, self._notify, self._enabled, self._hint, self._clock = sampler, notify, enabled, hint, clock
        self._streak = {"cpu": 0, "ram": 0}
        self._last_alert: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ the rules (one call = one 30-second check)
    def tick(self) -> list[str]:
        """Check once. Returns the kinds of alert shown (for tests)."""
        if not self._enabled():
            self._streak = {"cpu": 0, "ram": 0}
            return []
        try:
            s = self._sample()
        except Exception:
            return []                                       # a failed reading is never worth a message
        shown = []
        top = ", ".join(f"{name} ({pct:.0f}%)" for name, pct in (s.get("top") or [])[:2])
        self._streak["cpu"] = self._streak["cpu"] + 1 if s.get("cpu", 0) >= CPU_PERCENT else 0
        self._streak["ram"] = self._streak["ram"] + 1 if s.get("ram", 0) >= RAM_PERCENT else 0
        if self._streak["cpu"] >= CPU_TICKS and self._due("cpu"):
            self._say("cpu", "Your PC is slow", "It has been very busy for 3 minutes" + (f". Biggest: {top}" if top else "")
                      + f". Press {self._hint()} and ask Consiz why.")
            shown.append("cpu")
        if self._streak["ram"] >= RAM_TICKS and self._due("ram"):
            self._say("ram", "Memory is almost full", f"{s['ram']:.0f}% of memory has been in use for 2 minutes"
                      + (f". Biggest: {top}" if top else "") + f". Press {self._hint()} to ask Consiz.")
            shown.append("ram")
        free = s.get("disk_free_percent")
        if free is not None and free < DISK_FREE_PERCENT and self._due("disk"):
            self._say("disk", "Your disk is almost full", f"Drive {s.get('disk_drive', 'C:')} has only "
                      f"{s.get('disk_free_gb', '?')} GB free ({free:.0f}%). Press {self._hint()} to ask Consiz how to free space.")
            shown.append("disk")
        return shown

    def _due(self, kind: str) -> bool:
        last = self._last_alert.get(kind)
        return last is None or self._clock() - last >= COOLDOWN_S[kind]

    def _say(self, kind: str, title: str, text: str) -> None:
        self._last_alert[kind] = self._clock()
        try:
            self._notify(title, text)
        except Exception:
            pass

    # ------------------------------------------------------------------ the background thread
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="consiz-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(INTERVAL_S):
            self.tick()
