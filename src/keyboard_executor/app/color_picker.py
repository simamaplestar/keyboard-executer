"""滴管取色覆蓋層：開啟時擷全螢幕當背景，點擊處從截圖陣列取樣目標顏色 HSV。

覆蓋層是頂層視窗、無法讀自身像素；直接對實螢幕擷取又會被遮罩色汙染，故開啟時
先擷一張全螢幕截圖畫為背景（所見即所取），點擊時從那張截圖的 numpy 陣列取樣。
座標邏輯→實體像素沿用 region_picker.drag_scale。以 modal 對話框為 parent 才不被
modal 擋輸入（同 RegionPickerOverlay）。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QWidget

from keyboard_executor.app.region_picker import drag_scale
from keyboard_executor.app.template_preview import bgr_to_qimage
from keyboard_executor.core.geometry import Rect
from keyboard_executor.core.vision import sample_dominant_hsv


def _patch_around(image_bgr: np.ndarray, x: int, y: int, radius: int) -> np.ndarray:
    """截圖中 (x, y) 周圍 (2r+1)² patch，超出邊界自動夾住。"""
    h, w = image_bgr.shape[:2]
    cx = max(0, min(x, w - 1))
    cy = max(0, min(y, h - 1))
    return image_bgr[max(0, cy - radius):min(h, cy + radius + 1),
                     max(0, cx - radius):min(w, cx + radius + 1)]


class ColorPickerOverlay(QWidget):
    color_picked = Signal(int, int, int)     # HSV（OpenCV 範圍）
    cancelled = Signal()

    def __init__(self, capture_factory, parent=None):
        super().__init__(parent, Qt.WindowType.Window
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._capture_factory = capture_factory
        self._shot: np.ndarray | None = None
        self._qimage: QImage | None = None

    def open_fullscreen(self) -> None:
        geo = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(geo)
        scale = drag_scale(QGuiApplication.primaryScreen().devicePixelRatio())
        # 座標一律用 drag_scale 從邏輯換成擷取的實體像素單位；擷取回的影像尺寸即等於 rect，故取樣索引與截圖同一比例（與 template_capture 走 scale_factor 的路徑不同，v1 僅主螢幕）。
        rect = Rect(round(geo.x() * scale), round(geo.y() * scale),
                    round(geo.width() * scale), round(geo.height() * scale))
        self._shot = self._capture_factory().capture(rect)
        self._qimage = bgr_to_qimage(self._shot)
        self.show()
        self.raise_()
        self.activateWindow()

    def _pick(self, x: int, y: int) -> None:
        if self._shot is None:
            return
        scale = drag_scale(QGuiApplication.primaryScreen().devicePixelRatio())
        patch = _patch_around(self._shot, round(x * scale), round(y * scale), 2)
        h, s, v = sample_dominant_hsv(patch)
        self.close()
        self.color_picked.emit(h, s, v)

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        self._pick(int(pos.x()), int(pos.y()))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()

    def paintEvent(self, event) -> None:
        if self._qimage is not None:
            QPainter(self).drawImage(self.rect(), self._qimage)
