"""pynput 輸入模擬：macOS（CGEvent）與 Windows（SendInput）共用。"""
from __future__ import annotations

import time

from pynput.keyboard import Controller as KeyboardController
from pynput.mouse import Button
from pynput.mouse import Controller as MouseController

from keyboard_executor.platforms.base import InputBackend, MouseButton
from keyboard_executor.platforms.common.keymap import parse_key

_BUTTON = {
    MouseButton.LEFT: Button.left,
    MouseButton.RIGHT: Button.right,
    MouseButton.MIDDLE: Button.middle,
}

# 滑鼠移動後給前景程式反應時間（秒）；太短會導致部分程式收不到 hover/點擊位置
_SETTLE = 0.05
# 組合鍵按下後停留再放開的時間（秒）：0ms 會被輪詢式讀鍵（DirectInput/GetAsyncKeyState）
# 的遊戲在兩次輪詢間漏掉「修飾鍵＋主鍵同時按下」。40ms 跨得過至少 2 個 frame。
_COMBO_HOLD = 0.04


class PynputInputBackend(InputBackend):
    def __init__(self, keyboard=None, mouse=None, sleep=time.sleep):
        self._kb = keyboard if keyboard is not None else KeyboardController()
        self._mouse = mouse if mouse is not None else MouseController()
        self._sleep = sleep

    def key_press(self, key: str, hold_ms: int = 0) -> None:
        k = parse_key(key)
        self._kb.press(k)
        if hold_ms > 0:
            self._sleep(hold_ms / 1000)
        self._kb.release(k)

    def key_down(self, key: str) -> None:
        self._kb.press(parse_key(key))

    def key_up(self, key: str) -> None:
        self._kb.release(parse_key(key))

    def key_combo(self, keys: list[str]) -> None:
        self.key_combo_down(keys)
        self._sleep(_COMBO_HOLD)          # 預設 40ms：讓輪詢式遊戲抓得到同時按下
        self.key_combo_up(keys)

    def type_text(self, text: str) -> None:
        self._kb.type(text)

    def mouse_move(self, x: int, y: int) -> None:
        self._mouse.position = (x, y)

    def mouse_click(
        self, x: int, y: int, button: MouseButton = MouseButton.LEFT, count: int = 1
    ) -> None:
        self._mouse.position = (x, y)
        self._sleep(_SETTLE)
        self._mouse.click(_BUTTON[button], count)

    def mouse_click_checked(self, x, y, button=MouseButton.LEFT, count=1, *, check,
                            before_click=None, hold_ms=0):
        check()
        self._mouse.position = (x, y)
        self._checked_wait(_SETTLE, check)
        for _ in range(count):
            check()
            if before_click is not None:
                before_click()
            if hold_ms:
                self._mouse.press(_BUTTON[button])
                try:
                    self._sleep(hold_ms / 1000)
                finally:
                    self._mouse.release(_BUTTON[button])
            else:
                self._mouse.click(_BUTTON[button], 1)

    def _checked_wait(self, seconds, check):
        while seconds > 1e-9:
            check()
            step = min(.02, seconds)
            self._sleep(step)
            seconds -= step
        check()

    def mouse_drag_checked(self, from_x, from_y, to_x, to_y, button=MouseButton.LEFT,
                           *, check, before_press=None):
        check()
        self._mouse.position = (from_x, from_y)
        self._checked_wait(_SETTLE, check)
        if before_press is not None:
            before_press()
        b = _BUTTON[button]
        try:
            self._mouse.press(b)
            self._checked_wait(_SETTLE, check)
            self._mouse.position = (to_x, to_y)
            self._checked_wait(_SETTLE, check)
        finally:
            self._mouse.release(b)

    def scroll_checked(self, x, y, dx, dy, *, check):
        check()
        self._mouse.position = (x, y)
        self._checked_wait(_SETTLE, check)
        self._mouse.scroll(dx, dy)

    def mouse_drag(
        self, from_x: int, from_y: int, to_x: int, to_y: int,
        button: MouseButton = MouseButton.LEFT,
    ) -> None:
        b = _BUTTON[button]
        self._mouse.position = (from_x, from_y)
        self._sleep(_SETTLE)
        self._mouse.press(b)
        self._sleep(_SETTLE)
        self._mouse.position = (to_x, to_y)
        self._sleep(_SETTLE)
        self._mouse.release(b)

    def scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._mouse.position = (x, y)
        self._sleep(_SETTLE)
        self._mouse.scroll(dx, dy)
