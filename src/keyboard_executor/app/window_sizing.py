"""頂層視窗尺寸治理：啟動尺寸不得超過目前螢幕的可用工作區。"""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication


_SCREEN_MARGIN = 32  # 預留系統視窗邊框與陰影，避免底部／右側拖曳邊界落到螢幕外


def bounded_window_size(available_width: int, available_height: int,
                        preferred_width: int, preferred_height: int,
                        margin: int = _SCREEN_MARGIN) -> tuple[int, int]:
    """把偏好尺寸限制在螢幕可用範圍內；純函式供無頭測試。"""
    usable_width = max(1, int(available_width) - max(0, int(margin)))
    usable_height = max(1, int(available_height) - max(0, int(margin)))
    return (min(max(1, int(preferred_width)), usable_width),
            min(max(1, int(preferred_height)), usable_height))


def fit_window_to_available_screen(window, preferred_width: int,
                                   preferred_height: int) -> tuple[int, int]:
    """依 window 所在螢幕縮小初始尺寸；取不到螢幕時沿用偏好尺寸。"""
    screen = window.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        size = (preferred_width, preferred_height)
    else:
        available = screen.availableGeometry()
        size = bounded_window_size(
            available.width(), available.height(), preferred_width, preferred_height)
    window.resize(*size)
    return size
