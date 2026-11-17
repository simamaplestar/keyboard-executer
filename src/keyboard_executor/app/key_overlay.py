"""錄製中的即時按鍵浮動窗：置頂顯示剛剛錄進腳本的按鍵。

存在理由：錄製時使用者人在遊戲視窗裡，錄製面板被遊戲蓋住，無從得知哪些鍵真的
被錄到——特別是特殊鍵曾經整批被靜默丟棄（見 platforms/common/hook_pynput.py
的 _canonical）。浮在最上層即時回饋，按了沒出現就是沒錄到，當場就發現。

視窗屬性刻意選成「不搶焦點」（WindowDoesNotAcceptFocus + WA_ShowWithoutActivating）：
錄製中焦點必須留在遊戲視窗，否則後續按鍵會送錯地方、連錄製本身都被打斷。

describe_event 是純邏輯（事件 → 短描述），與 Qt 無關，另有單元測試。
"""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from keyboard_executor.platforms.base import EventKind

_MAX_ITEMS = 10          # 保留的最近事件數（超過從左端捨去）
_TOP_MARGIN = 28         # 距螢幕頂端的距離
_SEPARATOR = "  ›  "

_BUTTON_LABELS = {"left": "左鍵", "right": "右鍵", "middle": "中鍵"}


def describe_event(event) -> str | None:
    """錄製事件 → 浮動窗上的短描述；不需顯示的事件回 None。

    只顯示「會產生動作」的那一刻：按鍵按下、滑鼠按下、滾輪。放開與滑鼠移動不顯示
    ——放開只更新修飾鍵狀態，移動在 full 模式下每 100ms 一筆，都會把畫面洗掉。
    """
    kind = event.kind
    if kind is EventKind.KEY_DOWN:
        return event.key
    if kind is EventKind.MOUSE_DOWN:
        name = _BUTTON_LABELS.get(str(event.button), str(event.button))
        return f"滑鼠{name}"
    if kind is EventKind.SCROLL:
        return "滾輪↑" if event.dy > 0 else "滾輪↓"
    return None


class KeyOverlay(QWidget):
    """置頂、不搶焦點的橫幅，顯示最近錄到的按鍵。"""

    def __init__(self, parent=None, max_items: int = _MAX_ITEMS):
        super().__init__(parent, Qt.WindowType.Tool
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        # 顯示時不奪取焦點：錄製中焦點必須留在遊戲視窗
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._items: deque[str] = deque(maxlen=max_items)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 11, 18, 11)
        layout.setSpacing(14)
        self.title_label = QLabel("● 錄製中")
        self.keys_label = QLabel("（等待按鍵……）")
        layout.addWidget(self.title_label)
        layout.addWidget(self.keys_label)
        self.setStyleSheet(
            "QWidget { background: rgba(20, 22, 28, 235);"
            " border: 1px solid rgba(255, 255, 255, 40); border-radius: 10px; }"
            "QLabel { color: #f2f4f8; font-size: 15px; border: none; }")
        self.title_label.setStyleSheet(
            "QLabel { color: #ff6b6b; font-weight: bold; border: none;"
            " border-right: 1px solid rgba(255, 255, 255, 45);"
            " padding-right: 14px; }")

    def push(self, text: str) -> None:
        """加入一筆按鍵描述並更新顯示（最新在最右）。"""
        self._items.append(text)
        self.keys_label.setText(_SEPARATOR.join(self._items))
        self.adjustSize()
        self._recentre()

    def clear(self) -> None:
        self._items.clear()
        self.keys_label.setText("（等待按鍵……）")

    def show_at_top(self) -> None:
        """在主螢幕頂端置中顯示。"""
        self.clear()
        self.adjustSize()
        self._recentre()
        self.show()
        self.raise_()

    def _recentre(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:       # offscreen 測試環境可能沒有螢幕
            return
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.top() + _TOP_MARGIN)
