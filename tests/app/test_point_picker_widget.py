"""取點覆蓋層：讀數內容、點擊發座標、Esc 取消。"""
import numpy as np
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from keyboard_executor.app.point_picker import PointPickerOverlay


class FakeCap:
    def __init__(self, image=None):
        self.image = image

    def capture(self, rect):
        return self.image


def test_pick_emits_screen_point(qapp):
    overlay = PointPickerOverlay(lambda: FakeCap())
    seen = []
    overlay.point_picked.connect(lambda x, y: seen.append((x, y)))
    overlay._pick(120, 90)
    assert seen == [(120, 90)]     # 未定位的覆蓋層 x()/y() 為 0


def test_readout_shows_screen_only_without_target_window(qapp):
    overlay = PointPickerOverlay(lambda: FakeCap())
    lines = overlay._readout_lines(300, 200)
    assert len(lines) == 1 and "300, 200" in lines[0]


def test_readout_includes_window_relative_when_available(qapp):
    """使用者要填的是視窗相對值，讀數必須把它一起顯示出來。"""
    overlay = PointPickerOverlay(lambda: FakeCap(),
                                 lambda x, y: (x - 100, y - 50))
    lines = overlay._readout_lines(300, 200)
    assert len(lines) == 2
    assert "300, 200" in lines[0] and "200, 150" in lines[1]


def test_move_updates_cursor(qapp):
    overlay = PointPickerOverlay(lambda: FakeCap())
    assert overlay._cursor is None
    overlay._move(40, 60)
    assert overlay._cursor == (40, 60)


def test_escape_emits_cancelled(qapp):
    overlay = PointPickerOverlay(lambda: FakeCap())
    seen = []
    overlay.cancelled.connect(lambda: seen.append(True))
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                    Qt.KeyboardModifier.NoModifier))
    assert seen == [True]


def test_paint_without_capture_does_not_crash(qapp):
    """截圖尚未載入時重繪不可炸（open_fullscreen 前的重繪）。"""
    overlay = PointPickerOverlay(lambda: FakeCap())
    overlay.resize(80, 60)
    overlay._move(10, 10)
    overlay.grab()      # 觸發 paintEvent


def test_paint_with_capture_and_readout(qapp):
    overlay = PointPickerOverlay(lambda: FakeCap(), lambda x, y: (x, y))
    overlay.resize(80, 60)
    overlay._qimage = None
    overlay._move(78, 58)    # 貼近右下角：讀數方塊要翻到游標另一側而不越界
    overlay.grab()
