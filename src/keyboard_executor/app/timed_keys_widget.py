"""定時技能編輯：每列「錄製按鍵＋每幾秒」，F1~F12、方向鍵等直接按一下就記錄。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from keyboard_executor.app.key_capture import _KeyCaptureEdit
from keyboard_executor.core.models import (
    ScriptValidationError, TimedKey, timed_keys_from_text, timed_keys_to_text,
)


_TAP_MS = 100      # 「按一下」實際按住時間（遊戲才收得到）


class _Row(QWidget):
    def __init__(self, item: TimedKey | None, on_remove, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.key_edit = _KeyCaptureEdit()
        lay.addWidget(self.key_edit, 1)
        lay.addWidget(QLabel("每"))
        self.seconds = QSpinBox()
        self.seconds.setRange(1, 36000)
        self.seconds.setSuffix(" 秒")
        self.seconds.setValue(120)
        lay.addWidget(self.seconds)
        # 按住秒數：0＝按一下；補飢餓度等需要長按的技能填秒數。
        self.hold = QDoubleSpinBox()
        self.hold.setRange(0, 30)
        self.hold.setDecimals(1)
        self.hold.setSingleStep(.5)
        self.hold.setPrefix("按住 ")
        self.hold.setSuffix(" 秒")
        self.hold.setSpecialValueText("按一下")
        lay.addWidget(self.hold)
        self.remove_button = QPushButton("刪除")
        self.remove_button.clicked.connect(lambda: on_remove(self))
        lay.addWidget(self.remove_button)
        self.wait_ms = 500
        if item is not None:
            self.key_edit.setText(item.key)
            self.seconds.setValue(max(1, int(round(item.interval_sec))))
            self.hold.setValue(0 if item.hold_ms <= _TAP_MS else item.hold_ms / 1000)
            self.wait_ms = item.wait_ms

    @property
    def hold_ms(self) -> int:
        value = self.hold.value()
        return _TAP_MS if value <= 0 else int(round(value * 1000))


class TimedKeysWidget(QWidget):
    """text()/setText() 沿用「1:120, f1:180」文字格式，方便存檔與測試。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._rows: list[_Row] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._rows_box = QVBoxLayout()
        outer.addLayout(self._rows_box)
        self.add_button = QPushButton("＋ 新增定時技能")
        self.add_button.setToolTip("按「錄製按鍵」後按一下技能鍵（F1~F12 也可以），再設定每幾秒放一次")
        self.add_button.clicked.connect(lambda: self.add_row())
        outer.addWidget(self.add_button)
        self.setText(text)

    def add_row(self, item: TimedKey | None = None) -> _Row:
        row = _Row(item, self._remove_row, self)
        self._rows.append(row)
        self._rows_box.addWidget(row)
        return row

    def _remove_row(self, row: _Row) -> None:
        self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def rows(self) -> list[_Row]:
        return list(self._rows)

    def items(self) -> tuple[TimedKey, ...]:
        """沒錄按鍵的列略過；按鍵不合法拋 ScriptValidationError。"""
        result = []
        for row in self._rows:
            key = row.key_edit.text().strip().lower()
            if not key:
                continue
            parsed = timed_keys_from_text(f"{key}:{row.seconds.value()}")[0]
            result.append(TimedKey(parsed.key, parsed.interval_sec, row.hold_ms, row.wait_ms))
        return tuple(result)

    def text(self) -> str:
        try:
            return timed_keys_to_text(self.items())
        except ScriptValidationError:
            return ""

    def setText(self, text: str) -> None:   # noqa: N802 - 與 QLineEdit 相同介面
        for row in list(self._rows):
            self._remove_row(row)
        for item in timed_keys_from_text(text or ""):
            self.add_row(item)
