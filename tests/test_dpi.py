"""T-06: DPI scaling and multi-monitor placement. The placement maths is pure, so every layout case is tested here
(the real screens were checked by eye at 125 %: see the checkpoint note)."""
import pytest

from consiz.platform.win32 import dpi

MAIN = (0, 0, 1920, 1040)                    # work area: 1080 high minus a 40 px taskbar
LEFT = (-1920, 0, 0, 1080)                   # a monitor to the LEFT of the main one: negative coordinates
ABOVE = (0, -1080, 1920, 0)                  # a monitor ABOVE the main one


def test_window_opens_just_below_right_of_the_cursor():
    assert dpi.place_near((600, 300), (525, 538), MAIN, gap=15) == (615, 315)


@pytest.mark.parametrize("point", [(1900, 300), (1919, 20), (5, 1030), (1900, 1030)])
def test_window_never_runs_off_the_main_screen(point):
    x, y = dpi.place_near(point, (525, 538), MAIN)
    left, top, right, bottom = MAIN
    assert left <= x and x + 525 <= right and top <= y and y + 538 <= bottom


@pytest.mark.parametrize("area,point", [(LEFT, (-100, 500)), (LEFT, (-1900, 20)), (ABOVE, (900, -50)), (ABOVE, (1900, -10))])
def test_window_stays_on_a_second_monitor_with_negative_coordinates(area, point):
    x, y = dpi.place_near(point, (525, 538), area)
    left, top, right, bottom = area
    assert left <= x and x + 525 <= right and top <= y and y + 538 <= bottom, (x, y)


def test_a_window_bigger_than_the_area_is_pinned_to_its_top_left():
    assert dpi.place_near((100, 100), (3000, 2000), MAIN) == (0, 0)


def test_scale_and_px(monkeypatch):
    monkeypatch.setenv("CONSIZ_UI_SCALE", "1.5")
    assert dpi.scale() == 1.5 and dpi.px(420) == 630 and dpi.px(14) == 21
    monkeypatch.setenv("CONSIZ_UI_SCALE", "1")
    assert dpi.px(420) == 420
    monkeypatch.setenv("CONSIZ_UI_SCALE", "garbage")
    assert dpi.scale() >= 1.0                                    # a bad override never breaks the UI


def test_work_area_is_a_real_rectangle_and_enable_is_idempotent():
    dpi.enable()
    dpi.enable()
    left, top, right, bottom = dpi.work_area_at(10, 10)
    assert right > left and bottom > top
    far = dpi.work_area_at(-99999, -99999)                       # a point on no monitor: the nearest one is used
    assert far[2] > far[0]


def test_popup_and_dialog_sizes_come_from_px():
    from consiz.platform.win32 import login, onboarding, popup
    assert popup.WIDTH == dpi.px(420)
    assert (login.WIDTH, login.HEIGHT) == (dpi.px(420), dpi.px(230))
    left, top, right, bottom = dpi.work_area_at(0, 0)
    assert onboarding.WIDTH <= dpi.px(490) and onboarding.HEIGHT <= dpi.px(455), "welcome window: compact"
    assert onboarding.WIDTH <= right - left and onboarding.HEIGHT <= bottom - top, "...and never bigger than the screen"


def test_fit_size_never_exceeds_the_screen_it_opens_on():
    small = (0, 0, 1366, 728)                              # a 1366x768 laptop minus the taskbar
    assert dpi.fit_size((775, 750), small) == (775, 669)     # too tall: shrunk to 92 % of the height
    assert dpi.fit_size((2000, 500), small) == (1256, 500)   # too wide
    assert dpi.fit_size((600, 400), small) == (600, 400), "a window that fits is left alone"
    assert dpi.fit_size((600, 400), (-1920, 0, 0, 1040)) == (600, 400), "a monitor to the left works too"
