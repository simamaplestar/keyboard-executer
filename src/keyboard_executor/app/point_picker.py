"""取點覆蓋層：凍結畫面 + 十字準星 + 即時座標讀數，點擊取得單一座標點。

畫面凍結的理由同 color_picker：覆蓋層是頂層視窗、讀不到自身像素，直接對實螢幕
擷取又會被遮罩色汙染，故開啟時先擷一張全螢幕截圖畫為背景（所見即所點）；順帶讓
使用者能慢慢對準會動的遊戲畫面。

讀數同時顯示螢幕座標與視窗相對座標——動作存的是視窗相對值（player._to_screen
回放時才加回視窗原點），使用者光看螢幕座標無從得知該填什麼。視窗相對值由呼叫端
注入的 to_window callable 計算，覆蓋層本身不做視窗查找；point_picked 發的是
Qt 邏輯螢幕座標，權威換算仍由呼叫端以 region_math 完成（責任分界同
RegionPickerOverlay）。以 modal 對話框為 parent 才不被 modal 擋輸入。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from keyboard_executor.app.region_picker import drag_scale
from keyboard_executor.app.template_preview import bgr_to_qimage
from keyboard_executor.core.geometry import Rect

_READOUT_OFFSET = 18       # 讀數方塊相對游標的位移，避免準星壓住文字
_READOUT_W = 168
_READOUT_H = 52


class PointPickerOverlay(QWidget):
    point_picked = Signal(int, int)    # Qt 邏輯螢幕座標
    cancelled = Signal()

    def __init__(self, capture_factory, to_window=None, parent=None):
        super().__init__(parent, Qt.WindowType.Window
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)     # 未按鍵也要收 move 才有即時讀數
        self._capture_factory = capture_factory
        self._to_window = to_window
        self._qimage: QImage | None = None
        self._cursor: tuple[int, int] | None = None

    def open_fullscreen(self) -> None:
        geo = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(geo)
        scale = drag_scale(QGuiApplication.primaryScreen().devicePixelRatio())
        rect = Rect(round(geo.x() * scale), round(geo.y() * scale),
                    round(geo.width() * scale), round(geo.height() * scale))
        self._qimage = bgr_to_qimage(self._capture_factory().capture(rect))
        self.show()
        self.raise_()
        self.activateWindow()          # 取得焦點才能收滑鼠移動與 Esc

    # -- 可測 seam（座標為覆蓋層內的 Qt 邏輯座標） --

    def _move(self, x: int, y: int) -> None:
        self._cursor = (x, y)
        self.update()

    def _pick(self, x: int, y: int) -> None:
        self.close()
        self.point_picked.emit(x + self.x(), y + self.y())

    def _readout_lines(self, x: int, y: int) -> list[str]:
        """讀數文字；to_window 未注入（無目標視窗）時只顯示螢幕座標。"""
        lines = [f"螢幕　{x + self.x()}, {y + self.y()}"]
        if self._to_window is not None:
            wx, wy = self._to_window(x + self.x(), y + self.y())
            lines.append(f"視窗　{wx}, {wy}")
        return lines

    # -- Qt 事件 --

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        self._move(int(pos.x()), int(pos.y()))

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        self._pick(int(pos.x()), int(pos.y()))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if self._qimage is not None:
            painter.drawImage(self.rect(), self._qimage)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 60))   # 輕遮罩：凸顯準星
        if self._cursor is None:
            return
        x, y = self._cursor
        painter.setPen(QPen(QColor(76, 154, 255), 1))        # 十字準星（accent）
        painter.drawLine(0, y, self.width(), y)
        painter.drawLine(x, 0, x, self.height())
        # 讀數方塊：靠近畫面右／下緣時翻到游標另一側，避免被切掉
        bx = x + _READOUT_OFFSET
        by = y + _READOUT_OFFSET
        if bx + _READOUT_W > self.width():
            bx = x - _READOUT_OFFSET - _READOUT_W
        if by + _READOUT_H > self.height():
            by = y - _READOUT_OFFSET - _READOUT_H
        painter.fillRect(bx, by, _READOUT_W, _READOUT_H, QColor(13, 17, 23, 235))
        painter.setPen(QPen(QColor(55, 67, 79), 1))
        painter.drawRect(bx, by, _READOUT_W, _READOUT_H)
        painter.setPen(QColor(230, 237, 243))
        painter.setFont(QFont("Microsoft JhengHei", 10))
        for i, line in enumerate(self._readout_lines(x, y)):
            painter.drawText(bx + 10, by + 21 + i * 20, line)
