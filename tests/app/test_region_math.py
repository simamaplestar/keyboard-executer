import pytest

from keyboard_executor.app.region_math import (
    normalize_drag,
    screen_point_to_window_point,
    screen_rect_to_window_region,
)
from keyboard_executor.core.geometry import Point, Rect


def test_normalize_drag_four_directions():
    expected = Rect(10, 20, 30, 40)
    corners = [(Point(10, 20), Point(40, 60)), (Point(40, 60), Point(10, 20)),
               (Point(40, 20), Point(10, 60)), (Point(10, 60), Point(40, 20))]
    for p1, p2 in corners:
        assert normalize_drag(p1, p2) == expected


def test_zero_size_drag_rejected():
    with pytest.raises(ValueError, match="框選範圍太小"):
        screen_rect_to_window_region(Rect(10, 10, 0, 5), Point(0, 0))
    with pytest.raises(ValueError, match="框選範圍太小"):
        screen_rect_to_window_region(Rect(10, 10, 5, 0), Point(0, 0))


def test_conversion_scale_1():
    region = screen_rect_to_window_region(Rect(150, 260, 30, 40), Point(100, 200))
    assert region == [50, 60, 30, 40]


def test_conversion_scale_2_rounds_and_allows_negative():
    region = screen_rect_to_window_region(Rect(40, 90, 15, 21), Point(100, 200),
                                          scale=2.0)
    assert region == [-20, -20, 30, 42]   # 框選超出視窗左上：x/y 允許負值


def test_point_conversion_scale_1():
    assert screen_point_to_window_point(150, 260, Point(100, 200)) == [50, 60]


def test_point_conversion_scale_2_rounds():
    # 邏輯座標 ×2 換成實體像素後再扣視窗原點
    assert screen_point_to_window_point(75, 105, Point(100, 200),
                                        scale=2.0) == [50, 10]


def test_point_conversion_allows_negative():
    # 點在視窗左上之外：允許負值（與 region 換算一致，不夾在 0）
    assert screen_point_to_window_point(10, 20, Point(100, 200)) == [-90, -180]


def test_point_conversion_inverts_player_to_screen():
    """存檔存視窗相對值、回放時 to_absolute 加回原點——兩者必須互為逆運算。"""
    from keyboard_executor.core.geometry import to_absolute

    origin = Point(320, 180)
    rel = screen_point_to_window_point(900, 640, origin)
    back = to_absolute(origin, Point(rel[0], rel[1]))
    assert (back.x, back.y) == (900, 640)


def test_drag_scale_platform_dependent():
    from keyboard_executor.app.region_picker import drag_scale
    assert drag_scale(2.0, _sys_platform="win32") == 2.0     # 輸入單位＝實體像素
    assert drag_scale(2.0, _sys_platform="darwin") == 1.0    # 輸入單位＝點＝Qt 邏輯座標
