"""T-01: the middle button belongs to Consiz only for a real click, in the right mode, in a non-excluded app."""
from consiz.platform.win32.mousegate import Act, GateSettings, MiddleGate, DEFAULT_EXCLUDED


def gate(mode="middle", extra=()):
    return MiddleGate(GateSettings.build(mode, extra))


def test_clean_click_is_consizs():
    g = gate()
    assert g.down(100, 100, False, "chrome.exe", 0.0) is Act.SWALLOW
    assert g.up(0.1) is Act.FIRE


def test_a_drag_is_given_back_to_the_app():
    g = gate()
    assert g.down(100, 100, False, "chrome.exe", 0.0) is Act.SWALLOW
    assert g.move(103, 101, 0.05) is Act.PASS                      # a tiny wobble is still a click
    assert g.move(130, 100, 0.1) is Act.DRAG                       # real movement: autoscroll / pan -> app
    assert g.up(0.5) is Act.PASS                                   # the release goes to the app too, no trigger


def test_excluded_apps_never_see_interference():
    for app in ("blender.exe", "Blender.EXE", "acad.exe"):
        g = gate()
        assert g.down(0, 0, False, app, 0.0) is Act.PASS
        assert g.up(0.1) is Act.PASS
    g = gate(extra=["MyCAD.exe"])
    assert g.down(0, 0, False, "mycad.exe", 0.0) is Act.PASS       # user-added exclusion, case-insensitive
    assert "blender.exe" in DEFAULT_EXCLUDED


def test_ctrl_middle_mode_only_takes_ctrl_clicks():
    g = gate("ctrl_middle")
    assert g.down(0, 0, False, "chrome.exe", 0.0) is Act.PASS and g.up(0.1) is Act.PASS     # plain click: untouched
    assert g.down(0, 0, True, "chrome.exe", 1.0) is Act.SWALLOW and g.up(1.1) is Act.FIRE   # Ctrl+click: Consiz


def test_hotkey_only_mode_never_touches_the_mouse():
    g = gate("hotkey")
    assert g.down(0, 0, True, "chrome.exe", 0.0) is Act.PASS and g.up(0.1) is Act.PASS


def test_unknown_mode_falls_back_to_the_default():
    assert GateSettings.build("banana", []).mode == "middle"
    assert GateSettings.build(None, None).mode == "middle"


def test_double_click_is_swallowed_only_while_we_hold_the_press():
    g = gate()
    assert g.double_click() is Act.PASS
    g.down(0, 0, False, "chrome.exe", 0.0)
    assert g.double_click() is Act.SWALLOW


def test_a_lost_release_is_forgotten_not_stuck_forever():
    g = gate()
    g.down(0, 0, False, "chrome.exe", 0.0)                         # release never arrives
    assert g.down(0, 0, False, "chrome.exe", 10.0) is Act.SWALLOW  # a new press 10 s later starts clean
    assert g.up(10.1) is Act.FIRE


def test_moves_are_ignored_when_no_press_is_pending():
    g = gate()
    assert g.move(500, 500, 0.0) is Act.PASS
    g.down(0, 0, False, "blender.exe", 0.0)                        # excluded app: passing state
    assert g.move(500, 500, 0.1) is Act.PASS


def test_movement_right_after_the_press_is_settling_not_a_drag():
    g = gate()
    g.down(100, 100, False, "chrome.exe", 0.0)
    assert g.move(160, 100, 0.01) is Act.PASS                      # inside the grace period: still a click
    assert g.up(0.05) is Act.FIRE


def test_a_wobble_under_ten_pixels_is_still_a_click():
    g = gate()
    g.down(100, 100, False, "chrome.exe", 0.0)
    assert g.move(108, 104, 0.2) is Act.PASS
    assert g.up(0.25) is Act.FIRE
