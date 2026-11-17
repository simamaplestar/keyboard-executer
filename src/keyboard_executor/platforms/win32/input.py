"""Windows 輸入實作。

``game_input_mode=True`` 時改走 pydirectinput（DirectInput scan code）；
``window_message_mode=True`` 時只對目前位於前景的腳本目標 HWND 送
WM_KEYDOWN/WM_KEYUP；``scan_pulse_mode=True`` 時用 pydirectinput 掃描碼把長按
切成短暫按下/放開脈衝。三者互斥。不做任何反偵測——目標若不接受該標準輸入路徑就
如實失效。

game mode 覆蓋：key_press/key_combo/mouse_click/mouse_drag 全走 pdi；type_text 只有
在每個字元都是 pdi 不需 Shift 就能打出來時（小寫字母、數字、空白、不需 Shift 的標點）
才逐字 pdi.press，否則 fallback pynput（pdi 打大寫或需 Shift 的符號會被吞掉、也打不出
非 ASCII 字元；文件化限制：遊戲內輸入中文請用剪貼簿或改用非 game mode）。滑鼠動作各步
間以 _SETTLE 等待，與共用層政策一致。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from keyboard_executor.platforms.base import MouseButton, WindowInfo
from keyboard_executor.platforms.common.input_pynput import _SETTLE, PynputInputBackend
from keyboard_executor.platforms.win32.keycodes import vk_for_key

_PDI_NOSHIFT = set("abcdefghijklmnopqrstuvwxyz0123456789 `-=[]\\;',./")

# pydirectinput 的 KEYBOARD_MAPPING（104 個鍵名）沒有數字鍵盤的 0-9——只有
# add/subtract/multiply/divide/decimal/numlock。缺的補上 Set-1 掃描碼，否則
# game/scan-pulse 模式送 numpad 數字時 pdi 查不到鍵名、靜默什麼都不做。
_PDI_NUMPAD_SCANCODES = {
    "num0": 0x52, "num1": 0x4F, "num2": 0x50, "num3": 0x51, "num4": 0x4B,
    "num5": 0x4C, "num6": 0x4D, "num7": 0x47, "num8": 0x48, "num9": 0x49,
}

# 本專案名稱 → pydirectinput 既有鍵名（pdi 用文字名稱表示 numpad 運算符號）
_PDI_ALIAS = {
    "num*": "multiply", "num+": "add", "num-": "subtract",
    "num.": "decimal", "num/": "divide",
    "menu": "apps",
}


def _pdi_key(name: str) -> str:
    """腳本按鍵名稱 → pydirectinput 鍵名。"""
    return _PDI_ALIAS.get(name, name)


_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_WM_SYSKEYDOWN = 0x0104
_WM_SYSKEYUP = 0x0105
_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12
_MESSAGE_REPEAT_INTERVAL_S = 0.03
_SCAN_PULSE_DOWN_S = 0.018
_SCAN_PULSE_RELEASE_S = 0.012
_EXTENDED_VKS = {
    0x21, 0x22, 0x23, 0x24,       # PageUp/PageDown/End/Home
    0x25, 0x26, 0x27, 0x28,       # Left/Up/Right/Down
    0x2D, 0x2E,                    # Insert/Delete
    0x5B, 0x5C, 0x5D,             # Windows/Menu
    0x6F, 0x90, 0xA3, 0xA5,       # Divide/NumLock/right Ctrl/right Alt
}


def _pdi_typeable(text: str) -> bool:
    """pydirectinput 逐字能打的字元：小寫字母、數字、空白與不需 Shift 的標點。
    大寫與需 Shift 的符號 pdi 不會自動加 Shift（會被吞掉），非 ASCII 也不行——這些
    改走 pynput 才打得出正確字元。"""
    return all(ch in _PDI_NOSHIFT for ch in text)


class Win32InputBackend(PynputInputBackend):
    def __init__(self, game_input_mode: bool = False,
                 window_message_mode: bool = False,
                 scan_pulse_mode: bool = False,
                 pdi=None, user32=None, literal_typer=None, **kwargs):
        if sum((game_input_mode, window_message_mode, scan_pulse_mode)) > 1:
            raise ValueError("鍵盤輸入模式不能同時啟用")
        super().__init__(**kwargs)
        self._pdi = None
        self._literal_typer = literal_typer
        self._window_message_mode = window_message_mode
        self._scan_pulse_mode = scan_pulse_mode
        self._message_hwnd: int | None = None
        self._message_held: set[int] = set()
        self._user32 = user32
        if game_input_mode or scan_pulse_mode:
            if pdi is None:
                import pydirectinput as pdi
            pdi.PAUSE = 0  # 由我們自己的 delay 動作控制節奏（注入的 pdi 也一併設定）
            mapping = getattr(pdi, "KEYBOARD_MAPPING", None)   # 注入的假 pdi 可能沒有
            if mapping is not None:
                for _name, _scan in _PDI_NUMPAD_SCANCODES.items():
                    mapping.setdefault(_name, _scan)
            self._pdi = pdi
        if window_message_mode and self._user32 is None:
            self._user32 = ctypes.windll.user32
            self._user32.GetForegroundWindow.restype = wintypes.HWND
            self._user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
            self._user32.MapVirtualKeyW.restype = wintypes.UINT
            self._user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
            self._user32.VkKeyScanW.restype = ctypes.c_short
            self._user32.PostMessageW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            self._user32.PostMessageW.restype = wintypes.BOOL

    def set_target_window(self, window: WindowInfo | None) -> None:
        """綁定訊息接收 HWND；其他輸入模式保留但不使用。"""
        if window is None:
            self._message_hwnd = None
            return
        native = window.handle
        if hasattr(native, "getHandle"):
            native = native.getHandle()
        try:
            self._message_hwnd = int(native)
        except (TypeError, ValueError) as e:
            raise RuntimeError("無法取得目標視窗的 Windows handle") from e

    def _message_key(self, key: str) -> tuple[int, list[int]]:
        vk = vk_for_key(key)
        if vk is not None:
            return vk, []
        n = key.strip()
        if len(n) != 1:
            raise ValueError(f"無法轉成 Windows 視窗訊息按鍵: {key!r}")
        raw = int(self._user32.VkKeyScanW(n))
        if raw == -1 or (raw & 0xFFFF) == 0xFFFF:
            raise ValueError(f"無法轉成 Windows 視窗訊息按鍵: {key!r}")
        modifiers: list[int] = []
        state = (raw >> 8) & 0xFF
        if state & 1:
            modifiers.append(_VK_SHIFT)
        if state & 2:
            modifiers.append(_VK_CONTROL)
        if state & 4:
            modifiers.append(_VK_MENU)
        return raw & 0xFF, modifiers

    def _post_message_key(self, vk: int, down: bool) -> None:
        hwnd = self._message_hwnd
        if hwnd is None:
            raise RuntimeError("前景視窗訊息模式尚未綁定目標視窗")
        foreground = self._user32.GetForegroundWindow()
        # Key-up for a key we pressed is cleanup, so allow that one release after a
        # focus change; new key-downs and unrelated releases remain foreground-only.
        if (not foreground or int(foreground) != hwnd) and (down or vk not in self._message_held):
            raise RuntimeError("目標視窗已不是前景視窗，已停止送出按鍵訊息")
        scan = int(self._user32.MapVirtualKeyW(vk, 0)) & 0xFF
        lparam = 1 | (scan << 16)
        if vk in _EXTENDED_VKS:
            lparam |= 1 << 24
        system = vk == _VK_MENU or _VK_MENU in self._message_held
        if down and vk in self._message_held:
            lparam |= 1 << 30  # 實體鍵盤自動重複：previous key state=1
        elif not down:
            lparam |= (1 << 30) | (1 << 31)
        message = (_WM_SYSKEYDOWN if down else _WM_SYSKEYUP) if system else (
            _WM_KEYDOWN if down else _WM_KEYUP)
        if not self._user32.PostMessageW(hwnd, message, vk, lparam):
            raise RuntimeError("無法將按鍵訊息送到目標視窗")
        if down:
            self._message_held.add(vk)
        else:
            self._message_held.discard(vk)

    def key_press(self, key: str, hold_ms: int = 0) -> None:
        if self._window_message_mode:
            self.key_down(key)
            if hold_ms > 0:
                self._sleep(hold_ms / 1000)
            self.key_up(key)
            return
        if self._pdi is None:
            return super().key_press(key, hold_ms)
        self._pdi.keyDown(_pdi_key(key))
        if hold_ms > 0:
            self._sleep(hold_ms / 1000)
        self._pdi.keyUp(_pdi_key(key))

    def key_down(self, key: str) -> None:
        if self._window_message_mode:
            vk, modifiers = self._message_key(key)
            for modifier in modifiers:
                self._post_message_key(modifier, True)
            self._post_message_key(vk, True)
            return
        if self._pdi is None:
            return super().key_down(key)
        self._pdi.keyDown(_pdi_key(key))

    def key_up(self, key: str) -> None:
        if self._window_message_mode:
            vk, modifiers = self._message_key(key)
            self._post_message_key(vk, False)
            for modifier in reversed(modifiers):
                self._post_message_key(modifier, False)
            return
        if self._pdi is None:
            return super().key_up(key)
        self._pdi.keyUp(_pdi_key(key))

    def key_repeat_interval(self, key: str) -> float | None:
        del key
        if self._window_message_mode:
            return _MESSAGE_REPEAT_INTERVAL_S
        if self._scan_pulse_mode:
            return _SCAN_PULSE_DOWN_S
        return None

    def key_repeat(self, key: str) -> float:
        if self._window_message_mode:
            vk, _modifiers = self._message_key(key)
            if vk not in self._message_held:
                raise RuntimeError("無法重複尚未按住的按鍵")
            self._post_message_key(vk, True)
            return 0.0
        if self._scan_pulse_mode:
            self._pdi.keyUp(_pdi_key(key))
            self._sleep(_SCAN_PULSE_RELEASE_S)
            self._pdi.keyDown(_pdi_key(key))
            return _SCAN_PULSE_RELEASE_S
        return super().key_repeat(key)

    def type_text(self, text: str) -> None:
        if self._pdi is None or not _pdi_typeable(text):
            return super().type_text(text)
        for ch in text:
            self._pdi.press(ch)

    def type_text_literal(self, text: str) -> None:
        from keyboard_executor.platforms.win32.text_input import send_unicode_text
        typer = self._literal_typer or send_unicode_text
        typer(text)

    def mouse_click(
        self, x: int, y: int, button: MouseButton = MouseButton.LEFT, count: int = 1
    ) -> None:
        if self._pdi is None:
            return super().mouse_click(x, y, button, count)
        self._pdi.moveTo(x, y)
        self._sleep(_SETTLE)
        for _ in range(count):
            self._pdi.click(button=str(button))

    def mouse_click_checked(self, x, y, button=MouseButton.LEFT, count=1, *, check,
                            before_click=None, hold_ms=0):
        if self._pdi is None:
            return super().mouse_click_checked(x, y, button, count, check=check,
                                               before_click=before_click, hold_ms=hold_ms)
        check()
        self._pdi.moveTo(x, y)
        self._checked_wait(_SETTLE, check)
        for _ in range(count):
            check()
            if before_click is not None:
                before_click()
            if hold_ms:
                self._pdi.mouseDown(button=str(button))
                try:
                    self._sleep(hold_ms / 1000)
                finally:
                    self._release_mouse(button)
            else:
                self._pdi.click(button=str(button))

    def _release_mouse(self, button):
        try:
            self._pdi.mouseUp(button=str(button))
        except Exception as exc:
            # Cleanup must still release after PyDirectInput's corner failsafe.
            release = getattr(self._pdi.mouseUp, '__wrapped__', None)
            if release is not None and isinstance(exc, getattr(self._pdi, 'FailSafeException', ())):
                release(button=str(button))
            raise

    def mouse_drag_checked(self, from_x, from_y, to_x, to_y, button=MouseButton.LEFT,
                           *, check, before_press=None):
        if self._pdi is None:
            return super().mouse_drag_checked(from_x, from_y, to_x, to_y, button,
                                              check=check, before_press=before_press)
        check()
        self._pdi.moveTo(from_x, from_y)
        self._checked_wait(_SETTLE, check)
        if before_press is not None:
            before_press()
        try:
            self._pdi.mouseDown(button=str(button))
            self._checked_wait(_SETTLE, check)
            self._pdi.moveTo(to_x, to_y)
            self._checked_wait(_SETTLE, check)
        finally:
            self._release_mouse(button)

    def mouse_drag(
        self, from_x: int, from_y: int, to_x: int, to_y: int,
        button: MouseButton = MouseButton.LEFT,
    ) -> None:
        if self._pdi is None:
            return super().mouse_drag(from_x, from_y, to_x, to_y, button)
        self._pdi.moveTo(from_x, from_y)
        self._sleep(_SETTLE)
        self._pdi.mouseDown(button=str(button))
        self._sleep(_SETTLE)
        self._pdi.moveTo(to_x, to_y)
        self._sleep(_SETTLE)
        self._pdi.mouseUp(button=str(button))
