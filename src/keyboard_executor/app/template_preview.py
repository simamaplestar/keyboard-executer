"""模板圖片預覽（模板管理與規則編輯器共用）。

模板是「圖像規則／圖像動作實際會去比對的那張圖」，但介面上一直只有名稱。看不到圖
的後果很具體：規則裡的模板名打錯一個字，要等到監看跑起來、靜默比對不到，才會發現。
把圖顯示出來，錯字當場就看得見。

bgr_to_qimage 收斂在此並由 color_picker / point_picker 共用——三處都要把 OpenCV 的
BGR 陣列轉成 Qt 影像，各寫一份遲早會分歧。
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel

from keyboard_executor.core.models import ScriptValidationError


def bgr_to_qimage(image_bgr: np.ndarray) -> QImage:
    """OpenCV 的 BGR 陣列 → QImage（copy() 讓 Qt 自己持有記憶體，不依賴原陣列存活）。"""
    rgb = np.ascontiguousarray(image_bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def load_pixmap(store, name: str, max_size: tuple[int, int]) -> QPixmap | None:
    """讀模板並縮到 max_size 內（維持比例）；名稱空白或讀不到回 None。

    放大不做——模板常是十幾像素的小圖示，拉大只會糊掉又看不出細節。
    """
    if not name or not name.strip():
        return None
    try:
        image = store.load_template(name.strip())
    except ScriptValidationError:
        return None
    pixmap = QPixmap.fromImage(bgr_to_qimage(image))
    if pixmap.isNull():
        return None
    max_w, max_h = max_size
    if pixmap.width() > max_w or pixmap.height() > max_h:
        pixmap = pixmap.scaled(max_w, max_h,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
    return pixmap


class TemplatePreview(QLabel):
    """依名稱顯示模板縮圖；沒有圖時顯示原因，不留一塊空白讓人猜。"""

    def __init__(self, store, max_size: tuple[int, int] = (240, 180), parent=None):
        super().__init__(parent)
        self._store = store
        self._max_size = max_size
        self._name = ""
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(max_size[1] // 2)
        self.setWordWrap(True)
        self.setObjectName("templatePreview")
        self.setStyleSheet(
            "QLabel#templatePreview { border: 1px solid rgba(255,255,255,30);"
            " border-radius: 6px; padding: 6px; }")
        self.show_template("")

    @property
    def name(self) -> str:
        return self._name

    def size_text(self) -> str:
        """目前模板的尺寸描述（供旁邊的說明標籤使用）；沒有圖時為空字串。"""
        if not self._name:
            return ""
        try:
            image = self._store.load_template(self._name)
        except ScriptValidationError:
            return ""
        h, w = image.shape[:2]
        return f"{w} × {h} px"

    def show_template(self, name: str) -> None:
        self._name = (name or "").strip()
        if not self._name:
            self.setPixmap(QPixmap())
            self.setText("（未指定模板）")
            return
        pixmap = load_pixmap(self._store, self._name, self._max_size)
        if pixmap is None:
            self.setPixmap(QPixmap())
            # 規則編輯器最重要的一行：名稱打錯時當場看到，而不是等監看靜默失敗
            self.setText(f"找不到模板「{self._name}」")
            return
        self.setText("")
        self.setPixmap(pixmap)
