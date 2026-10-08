"""Decides, for every middle-button press, whether Consiz takes it or the app underneath keeps it (T-01).

Pure logic — no Windows calls — so every case is unit-tested. The mouse hook (trigger.py) feeds it events and
carries out the answer.

Why: swallowing the middle button everywhere breaks "open link in new tab", tab close, autoscroll and
middle-drag panning in CAD/3D tools. So Consiz only keeps a click that really was a CLICK, in an app that is not
excluded, in the mode the user chose — and gives everything else back untouched:

  mode "middle"       a middle CLICK is Consiz's. If nothing is selected the click is re-sent to the app
                      (the caller does that when the trigger reports "passthrough").
  mode "ctrl_middle"  only Ctrl + middle click is Consiz's; plain middle clicks are never touched.
  mode "hotkey"       the mouse is never touched; use Ctrl+Alt+S / Ctrl+Alt+A.
  a DRAG (button held + mouse moved) always belongs to the app (autoscroll, panning).
  paused (tray "Pause Consiz", or a full-screen app is in front): nothing is Consiz's.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

MODES = ("middle", "ctrl_middle", "hotkey")
DEFAULT_MODE = "middle"
DRAG_PIXELS = 10                   # moved further than this while held = a drag, not a click
DRAG_GRACE_SECONDS = 0.04          # movement in the first moments after the press is hand/mouse settling, not a drag
STALE_SECONDS = 5.0                # a press with no matching release (lost event) is forgotten

# Programs where the middle button is part of the work (pan / orbit / scroll). Users can add more.
DEFAULT_EXCLUDED = frozenset({
    "blender.exe", "acad.exe", "fusion360.exe", "3dsmax.exe", "maya.exe", "sketchup.exe", "solidworks.exe",
    "sldworks.exe", "revit.exe", "rhino.exe", "unity.exe", "unrealeditor.exe", "godot.exe", "zbrush.exe",
})


class Act(Enum):
    PASS = "pass"          # let this event through to the app untouched
    SWALLOW = "swallow"    # Consiz keeps it (button pressed; waiting to see click vs drag)
    FIRE = "fire"          # a clean click completed: swallow the release and run Consiz
    DRAG = "drag"          # it turned into a drag: give the app its button press back, then pass the move


@dataclass
class GateSettings:
    mode: str = DEFAULT_MODE
    excluded: frozenset = field(default_factory=lambda: DEFAULT_EXCLUDED)

    @staticmethod
    def build(mode: str | None, extra_excluded) -> "GateSettings":
        m = mode if mode in MODES else DEFAULT_MODE
        extra = {str(a).strip().lower() for a in (extra_excluded or []) if str(a).strip()}
        return GateSettings(m, frozenset(DEFAULT_EXCLUDED | extra))


class MiddleGate:
    IDLE, PENDING, PASSING = "idle", "pending", "passing"

    def __init__(self, settings: GateSettings | None = None):
        self.settings = settings or GateSettings()
        self.state = self.IDLE
        self._origin = (0, 0)
        self._since = 0.0

    @property
    def pending(self) -> bool:
        return self.state == self.PENDING

    def down(self, x: int, y: int, ctrl_held: bool, foreground_app: str, now: float, paused: bool = False) -> Act:
        self._forget_if_stale(now)
        self._since = now
        s = self.settings
        if paused or s.mode == "hotkey" or (foreground_app or "").lower() in s.excluded or (s.mode == "ctrl_middle" and not ctrl_held):
            self.state = self.PASSING          # not ours: the app gets this press AND its release
            return Act.PASS
        self.state, self._origin, self._since = self.PENDING, (x, y), now
        return Act.SWALLOW

    def move(self, x: int, y: int, now: float) -> Act:
        if self.state != self.PENDING or now - self._since < DRAG_GRACE_SECONDS:
            return Act.PASS
        if math.hypot(x - self._origin[0], y - self._origin[1]) > DRAG_PIXELS:
            self.state = self.PASSING          # a drag: autoscroll / pan belongs to the app
            return Act.DRAG
        return Act.PASS

    def up(self, now: float) -> Act:
        was = self.state
        self.state = self.IDLE
        return Act.FIRE if was == self.PENDING else Act.PASS

    def double_click(self) -> Act:
        return Act.SWALLOW if self.state == self.PENDING else Act.PASS

    def _forget_if_stale(self, now: float) -> None:
        if self.state != self.IDLE and now - self._since > STALE_SECONDS:
            self.state = self.IDLE
