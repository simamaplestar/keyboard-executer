"""Windows 系統級全域熱鍵（RegisterHotKey）：緊急停止的可靠後盾。

遊戲（尤其含反作弊）常擋掉使用者態的 WH_KEYBOARD_LL 低階鍵盤 hook（pynput），
使 F10 等熱鍵完全收不到（實測：滑鼠角落 failsafe 仍有效，但任何鍵盤鍵都收不到）。
RegisterHotKey 由 OS 處理、不經低階 hook 鏈，對遊戲較可靠。僅 Windows 使用；其他
平台仍以 pynput guard／滑鼠左上角為準。
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

from keyboard_executor.platforms.win32.keycodes import hotkey_to_vks, vk_for_key

logger = logging.getLogger(__name__)

_WM_HOTKEY = 0x0312
_MOD_NOREPEAT = 0x4000

class WindowsHotkey(QAbstractNativeEventFilter):
    """RegisterHotKey ＋ 攔 WM_HOTKEY。register() 成功後把本物件
    installNativeEventFilter 到 QApplication；觸發時呼叫 on_trigger。"""

    def __init__(self, on_trigger, hotkey_id: int = 0xB33F):
        super().__init__()
        self._on_trigger = on_trigger
        self._id = hotkey_id
        self._registered = False
        self._user32 = ctypes.windll.user32
        self._user32.RegisterHotKey.argtypes = [
            wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL

    def register(self, key_name: str) -> bool:
        vk = vk_for_key(key_name)
        if vk is None:
            return False
        self.unregister()
        ok = bool(self._user32.RegisterHotKey(None, self._id, _MOD_NOREPEAT, vk))
        self._registered = ok
        return ok

    def unregister(self) -> None:
        if self._registered:
            try:
                self._user32.UnregisterHotKey(None, self._id)
            except Exception:
                pass
            self._registered = False

    def nativeEventFilter(self, event_type, message):   # noqa: N802
        try:
            et = bytes(event_type)
        except Exception:
            et = event_type
        if et == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == _WM_HOTKEY and msg.wParam == self._id:
                try:
                    self._on_trigger()
                except Exception:
                    logger.exception("緊急停止熱鍵處理失敗")
        return False, 0
