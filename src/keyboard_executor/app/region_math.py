"""區域框選幾何（純 Python，無 Qt import）。

拖曳座標為 Qt 邏輯座標；scale＝Qt 邏輯座標 → 平台輸入座標單位的倍率
（region_picker.drag_scale：macOS 1.0、Windows devicePixelRatio）；
win_origin 為目標視窗左上角（輸入單位，pywinctl 幾何）。"""
from __future__ import annotations

from keyboard_executor.core.geometry import Point, Rect


def normalize_drag(p1: Point, p2: Point) -> Rect:
    """任意方向拖曳的兩角 → 正規化 Rect（原點取 min、寬高取絕對值）。"""
    return Rect(min(p1.x, p2.x), min(p1.y, p2.y),
                abs(p1.x - p2.x), abs(p1.y - p2.y))


def screen_point_to_window_point(x: int, y: int, win_origin: Point,
                                 scale: float = 1.0) -> list[int]:
    """螢幕點（Qt 邏輯座標）→ 視窗相對 [x, y]（輸入單位）。

    與 screen_rect_to_window_region 同一套換算，只是少了寬高：先把邏輯座標乘
    scale 換成輸入單位，再扣掉視窗原點。x/y 允許負值（點在視窗左上之外）。
    這正是 player._to_screen 的逆運算——存檔存視窗相對值，回放時再加回原點。"""
    return [round(x * scale) - win_origin.x, round(y * scale) - win_origin.y]


def screen_rect_to_window_region(drag_rect: Rect, win_origin: Point,
                                 scale: float = 1.0) -> list[int]:
    """螢幕拖曳矩形（Qt 邏輯座標）→ 視窗相對 region [x, y, w, h]（輸入單位）。
    寬高 <= 0 拋 ValueError（繁中）；x/y 允許負值（框選超出視窗左上）。"""
    width = round(drag_rect.width * scale)
    height = round(drag_rect.height * scale)
    if width <= 0 or height <= 0:
        raise ValueError("框選範圍太小，請重新拖曳")
    return [round(drag_rect.x * scale) - win_origin.x,
            round(drag_rect.y * scale) - win_origin.y, width, height]
