"""按鍵擷取輸入元件（共用）：點欄位後按下的鍵即被記錄成 keynames 的權威名稱。

腳本編輯器的按鍵欄與設定頁的熱鍵欄共用，確保存的值就是輸入 hook（key_to_name）
會送出的小寫 canonical 名稱——避免手打大小寫/別名不一致（緊急停止熱鍵尤其要一致）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


def _special_key_map() -> dict:
    K = Qt.Key
    m = {
        K.Key_Up: "up", K.Key_Down: "down", K.Key_Left: "left", K.Key_Right: "right",
        K.Key_Return: "enter", K.Key_Enter: "enter", K.Key_Escape: "esc",
        K.Key_Tab: "tab", K.Key_Backtab: "tab", K.Key_Space: "space",
        K.Key_Backspace: "backspace", K.Key_Delete: "delete",
        K.Key_Insert: "insert", K.Key_Home: "home", K.Key_End: "end",
        K.Key_PageUp: "pageup", K.Key_PageDown: "pagedown",
        K.Key_CapsLock: "capslock", K.Key_NumLock: "numlock",
        K.Key_ScrollLock: "scrolllock", K.Key_Print: "printscreen",
        K.Key_Pause: "pause", K.Key_Menu: "menu",
    }
    return {int(k): v for k, v in m.items()}


def _keypad_map() -> dict:
    """數字鍵盤：Qt 用「一般鍵碼 ＋ KeypadModifier」表示，鍵碼本身與主鍵盤相同，
    必須先看修飾位元才分得出來（與錄製端靠 vk 區分是同一件事，見 keymap.is_numpad）。"""
    K = Qt.Key
    m = {getattr(K, f"Key_{i}"): f"num{i}" for i in range(10)}
    m.update({K.Key_Plus: "num+", K.Key_Minus: "num-", K.Key_Asterisk: "num*",
              K.Key_Slash: "num/", K.Key_Period: "num."})
    return {int(k): v for k, v in m.items()}


_QT_SPECIAL = _special_key_map()
_QT_KEYPAD = _keypad_map()
_QT_MODS = {
    int(Qt.Key.Key_Control): "ctrl", int(Qt.Key.Key_Shift): "shift",
    int(Qt.Key.Key_Alt): "alt", int(Qt.Key.Key_Meta): "win",
    int(Qt.Key.Key_Super_L): "win", int(Qt.Key.Key_Super_R): "win",
}
_F1 = int(Qt.Key.Key_F1)
_ALL_MODS = ("ctrl", "alt", "shift", "win")


def _qt_key_to_name(event) -> str | None:
    """QKeyEvent → keynames 的權威按鍵名（方向鍵→up/down/left/right、F 鍵→f1…、
    可列印字元→小寫）。無法對應（如純組合鍵前導、未知鍵）回傳 None。"""
    k = event.key()
    # numpad 先判：Key_7 在主鍵盤與數字鍵盤上是同一個鍵碼，只有 KeypadModifier 分得出來
    if event.modifiers() & Qt.KeyboardModifier.KeypadModifier and k in _QT_KEYPAD:
        return _QT_KEYPAD[k]
    if k in _QT_SPECIAL:
        return _QT_SPECIAL[k]
    if _F1 <= k <= _F1 + 19:
        return f"f{k - _F1 + 1}"
    if k in _QT_MODS:
        return _QT_MODS[k]
    t = event.text()
    if t and len(t) == 1 and t.isprintable() and not t.isspace():
        return t.lower()
    return None


def _modifier_names(mods) -> list[str]:
    out = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        out.append("ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        out.append("alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        out.append("shift")
    if mods & Qt.KeyboardModifier.MetaModifier:
        out.append("win")
    return out


class _ClickLine(QLineEdit):
    """可被點擊觸發的唯讀顯示框（點它即開始錄製按鍵）。"""

    clicked = Signal()

    def mousePressEvent(self, event):   # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)


class _KeyCaptureEdit(QWidget):
    """按鍵擷取輸入：點欄位（或「錄製按鍵」）後，下一次按下的鍵即被記錄，免去手打
    名稱、方向鍵等特殊鍵也直覺。combo=True 時記錄整組組合鍵（如 ctrl+shift+s）。"""

    def __init__(self, combo: bool = False, parent=None):
        super().__init__(parent)
        self._combo = combo
        self._value = ""
        self._listening = False
        self._pressed: list[str] = []      # 錄製期間按過的鍵名（累積、依序，用於輸出）
        self._held: set[int] = set()        # 目前仍按著的鍵碼（全放開才定案）
        # 以 Qt 鍵碼（event.key()）追蹤按住狀態：放開事件在部分平台沒有 text()，
        # 用鍵名會抓不到，鍵碼在按下/放開都一定有。
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._display = _ClickLine()
        self._display.setReadOnly(True)
        self._display.setPlaceholderText(
            "點這裡再按一個組合鍵" if combo else "點這裡再按一個鍵")
        self._btn = QPushButton("錄製按鍵")
        lay.addWidget(self._display, 1)
        lay.addWidget(self._btn)
        self._btn.clicked.connect(self._start)
        self._display.clicked.connect(self._start)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _start(self) -> None:
        self._listening = True
        self._pressed = []
        self._held = set()
        self._display.setText("請按一個鍵…（Esc 取消）")
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        if self.isVisible():
            self.grabKeyboard()

    def _stop(self) -> None:
        self._listening = False
        self.releaseKeyboard()
        self._display.setText(self._value)

    def keyPressEvent(self, event):   # noqa: N802
        if not self._listening:
            super().keyPressEvent(event)
            return
        if event.key() == int(Qt.Key.Key_Escape):
            self._stop()          # Esc＝取消錄製（保留原值）
            return
        if event.isAutoRepeat():
            return                # 按住的自動重複不算新按鍵
        name = _qt_key_to_name(event)
        if name is None:
            return
        if not self._combo:
            self._value = name
            self._stop()
            return
        # combo：累積按下的鍵（含事件上的 modifiers 位元）；等「全部鍵放開」才定案，
        # 這樣按住修飾鍵、依序點主鍵（不必同時按著）也收得到全部鍵。
        for m in _modifier_names(event.modifiers()):
            if m not in self._pressed:
                self._pressed.append(m)
        if name not in self._pressed:
            self._pressed.append(name)
        self._held.add(int(event.key()))

    def keyReleaseEvent(self, event):   # noqa: N802
        if not self._listening or not self._combo:
            super().keyReleaseEvent(event)
            return
        if event.isAutoRepeat():
            return
        self._held.discard(int(event.key()))
        if self._held:
            return                # 還按著其他鍵 → 繼續累積，等全部放開才定案
        # 全部鍵已放開：至少一個非修飾鍵才定案（只按修飾鍵則重來、保留監聽）
        if any(k not in _ALL_MODS for k in self._pressed):
            self._commit()
            self._stop()
        else:
            self._pressed = []

    def _commit(self) -> None:
        mods = [m for m in _ALL_MODS if m in self._pressed]
        mains = [k for k in self._pressed if k not in _ALL_MODS]
        self._value = "+".join(mods + mains)

    def text(self) -> str:
        return self._value

    def setText(self, value: str) -> None:
        self._value = value or ""
        self._display.setText(self._value)
