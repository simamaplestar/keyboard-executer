"""模板管理對話框（M4 待辦 #4）：列出 templates/、預覽圖片、刪除（附繁中確認）。

薄件：清單與刪除直接走 TemplateStore（list_names/delete 為 M4 已建 seam），
confirm 注入供測試，預設 confirm_delete。刪除引用中的模板不做連動檢查
（規則/腳本執行時會以「找不到模板」如實回報，spec §10）。

清單每項帶縮圖、選取後在右側放大顯示：模板是「比對時實際會找的那張圖」，只列名稱
的話，要刪掉哪張、哪張是舊的重複擷取，全靠記憶。有圖才看得出來。
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from keyboard_executor.app.confirm import confirm_delete
from keyboard_executor.app.template_preview import TemplatePreview, load_pixmap
from keyboard_executor.app.window_sizing import fit_window_to_available_screen
from keyboard_executor.core.models import ScriptValidationError

_THUMB = (48, 48)          # 清單縮圖
_PREVIEW = (320, 240)      # 右側大預覽


class TemplateManagerDialog(QDialog):
    def __init__(self, store, confirm=None, parent=None):
        super().__init__(parent)
        self._store = store
        self._confirm = confirm if confirm is not None else partial(confirm_delete, self)
        self.setWindowTitle("模板管理")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("模板（PNG，供 *_image 動作與 image 規則引用）"))

        body = QHBoxLayout()
        self.template_list = QListWidget()
        self.template_list.setIconSize(QSize(*_THUMB))
        body.addWidget(self.template_list, stretch=1)

        side = QVBoxLayout()
        self.preview = TemplatePreview(store, max_size=_PREVIEW)
        side.addWidget(self.preview, stretch=1)
        self.size_label = QLabel("")
        self.size_label.setObjectName("detail")
        side.addWidget(self.size_label)
        body.addLayout(side, stretch=1)
        layout.addLayout(body, stretch=1)

        self.delete_button = QPushButton("刪除")
        self.delete_button.setProperty("variant", "danger")
        layout.addWidget(self.delete_button)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.delete_button.clicked.connect(self._on_delete)
        self.template_list.currentItemChanged.connect(self._on_selection_changed)
        self.refresh()
        fit_window_to_available_screen(self, 640, 460)

    def refresh(self) -> None:
        self.template_list.clear()
        for name in self._store.list_names():
            item = QListWidgetItem(name)
            pixmap = load_pixmap(self._store, name, _THUMB)
            if pixmap is not None:
                item.setIcon(QIcon(pixmap))
            self.template_list.addItem(item)
        if self.template_list.count():
            self.template_list.setCurrentRow(0)     # 開啟即看到第一張，不必先點
        else:
            self._show(None)

    def _on_selection_changed(self, current, _previous=None) -> None:
        self._show(current.text() if current is not None else None)

    def _show(self, name) -> None:
        self.preview.show_template(name or "")
        self.size_label.setText(self.preview.size_text())

    def _on_delete(self) -> None:
        item = self.template_list.currentItem()
        if item is None:
            self.status_label.setText("請先選取要刪除的模板")
            return
        name = item.text()
        if not self._confirm(f"確定刪除模板「{name}」？引用它的規則與腳本將失效。"):
            return
        try:
            self._store.delete(name)
        except ScriptValidationError as e:
            self.status_label.setText(f"模板刪除失敗：{e}")
            return
        self.status_label.setText(f"已刪除模板「{name}」")
        self.refresh()
