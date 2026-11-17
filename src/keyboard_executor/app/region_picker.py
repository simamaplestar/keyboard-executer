"""凍結畫面的全螢幕區域框選覆蓋層（spec §9）＋ Qt 邏輯座標→輸入單位倍率。

薄件：拖曳幾何純邏輯在 region_math；本檔只做覆蓋層繪製與滑鼠事件轉發
（_begin/_update/_finish 為可測 seam）。Esc 取消。region_selected 回傳的
Rect 為 Qt 邏輯座標——呼叫端以 drag_scale() 換算輸入單位後交
screen_rect_to_window_region() 得視窗相對 region。

規則編輯器是 modal 視窗；框選遮罩取得焦點時，Windows 可能把整個應用程式視窗群組
一起拉到目標視窗前面。若只畫半透明遮罩，使用者就會看見編輯器蓋回來。可注入
capture_factory，在遮罩 show() 前先凍結目標畫面並以它當背景；模板擷取也能直接從
同一張未受遮罩汙染的快照裁切。"""
from __future__ import annotations

import sys

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from keyboard_executor.app.region_math import normalize_drag
from keyboard_executor.app.template_preview import bgr_to_qimage
from keyboard_executor.core.geometry import Point, Rect


def drag_scale(device_pixel_ratio: float, _sys_platform=None) -> float:
    """Qt 邏輯座標 → 平台輸入座標單位的倍率（sys.platform 沿用 cli 權限檢查的
    已核准例外模式，注入供測試）：Windows 輸入單位為實體像素 →
    devicePixelRatio；macOS 為點（Qt 邏輯座標即點）→ 1.0。"""
    plat = _sys_platform if _sys_platform is not None else sys.platform
    return device_pixel_ratio if plat == "win32" else 1.0


class RegionPickerOverlay(QWidget):
    region_selected = Signal(object)   # geometry.Rect（Qt 邏輯座標，已正規化）
    cancelled = Signal()

    def __init__(self, parent=None, capture_factory=None):
        # parent 必要：規則編輯器是 modal 對話框，覆蓋層若無 parent 會被 modal 擋掉
        # 全部輸入（有遮罩但不能框選、Esc 也無效、卡在全螢幕）。加 Qt.Window 讓它
        # 即使有 parent 仍是獨立的頂層視窗。
        super().__init__(parent, Qt.WindowType.Window
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._capture_factory = capture_factory
        self._shot: np.ndarray | None = None
        self._qimage: QImage | None = None
        self._scale = 1.0
        self._start: Point | None = None
        self._current: Point | None = None

    def open_fullscreen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry()
        self.setGeometry(geo)
        self._scale = drag_scale(screen.devicePixelRatio())
        if self._capture_factory is not None:
            capture_rect = Rect(round(geo.x() * self._scale),
                                round(geo.y() * self._scale),
                                round(geo.width() * self._scale),
                                round(geo.height() * self._scale))
            self._shot = self._capture_factory().capture(capture_rect)
            self._qimage = bgr_to_qimage(self._shot)
        self.show()
        self.raise_()
        self.activateWindow()          # 確保取得輸入焦點，能接滑鼠拖曳與 Esc

    def captured_region(self, rect: Rect) -> np.ndarray | None:
        """從開啟遮罩前的乾淨快照裁切全域 Qt 邏輯 rect；無快照時回 None。"""
        if self._shot is None:
            return None
        x0 = round((rect.x - self.x()) * self._scale)
        y0 = round((rect.y - self.y()) * self._scale)
        x1 = round((rect.x + rect.width - self.x()) * self._scale)
        y1 = round((rect.y + rect.height - self.y()) * self._scale)
        height, width = self._shot.shape[:2]
        x0, x1 = max(0, x0), min(width, x1)
        y0, y1 = max(0, y0), min(height, y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return self._shot[y0:y1, x0:x1].copy()

    # -- 可測 seam（滑鼠事件轉發到這裡；座標為 Qt 邏輯的螢幕絕對座標） --

    def _begin(self, x: int, y: int) -> None:
        self._start = Point(x, y)
        self._current = Point(x, y)
        self.update()

    def _update(self, x: int, y: int) -> None:
        if self._start is None:
            return
        self._current = Point(x, y)
        self.update()

    def _finish(self, x: int, y: int) -> None:
        if self._start is None:
            return
        rect = normalize_drag(self._start, Point(x, y))
        self._start = None
        self._current = None
        self.close()
        self.region_selected.emit(rect)

    # -- Qt 事件（thin：加上覆蓋層自身位移換成螢幕座標） --

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        self._begin(int(pos.x()) + self.x(), int(pos.y()) + self.y())

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        self._update(int(pos.x()) + self.x(), int(pos.y()) + self.y())

    def mouseReleaseEvent(self, event) -> None:
        pos = event.position()
        self._finish(int(pos.x()) + self.x(), int(pos.y()) + self.y())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if self._qimage is not None:
            painter.drawImage(self.rect(), self._qimage)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))   # 半透明遮罩
        if self._start is not None and self._current is not None:
            rect = normalize_drag(self._start, self._current)
            painter.setPen(QPen(QColor(255, 60, 60), 2))
            painter.drawRect(rect.x - self.x(), rect.y - self.y(),
                             rect.width, rect.height)
