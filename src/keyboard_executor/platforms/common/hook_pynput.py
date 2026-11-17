"""pynput 全域輸入監聽：把 keyboard/mouse Listener callbacks 轉為 InputEvent。

macOS 需要「輸入監控」權限；缺權限時 pynput 可能靜默收不到事件（不一定拋錯），
CLI 層以繁中訊息提示（見 cli.py）。Listener 類注入供測試；None 時 lazy import
真實 pynput Listener（與 win32 input 的 pdi 注入模式一致）。
"""
from __future__ import annotations

import time
from typing import Callable

from keyboard_executor.platforms.base import (
    EventKind,
    InputEvent,
    InputHook,
    MouseButton,
)
from keyboard_executor.platforms.common.keymap import is_numpad, key_to_name

_BUTTON_NAMES = {
    "left": MouseButton.LEFT,
    "right": MouseButton.RIGHT,
    "middle": MouseButton.MIDDLE,
}


def _is_char_key(key) -> bool:
    """是否為「帶字元的按鍵」——唯一需要 canonical 正規化的類別。

    以 duck typing 判斷而非 isinstance(KeyCode)：本模組刻意不 import pynput，
    測試才能注入不依賴 pynput 的假按鍵物件。pynput 的 Key 是 enum，成員本身沒有
    .char（字元藏在 .value 這個 KeyCode 裡），因此特殊鍵不會被誤判。
    """
    return getattr(key, "char", None) is not None


class PynputInputHook(InputHook):
    def __init__(self, keyboard_listener_cls=None, mouse_listener_cls=None,
                 clock=time.monotonic):
        self._kb_cls = keyboard_listener_cls
        self._mouse_cls = mouse_listener_cls
        self._clock = clock
        self._kb_listener = None
        self._mouse_listener = None
        self._on_event: Callable[[InputEvent], None] | None = None

    def start(self, on_event: Callable[[InputEvent], None]) -> None:
        if self._kb_listener is not None:
            raise RuntimeError("輸入監聽已啟動，不能重複啟動")
        kb_cls = self._kb_cls
        mouse_cls = self._mouse_cls
        if kb_cls is None:
            from pynput import keyboard
            kb_cls = keyboard.Listener
        if mouse_cls is None:
            from pynput import mouse
            mouse_cls = mouse.Listener
        self._on_event = on_event
        self._kb_listener = kb_cls(on_press=self._on_press, on_release=self._on_release)
        self._mouse_listener = mouse_cls(
            on_move=self._on_move, on_click=self._on_click, on_scroll=self._on_scroll)
        try:
            self._kb_listener.start()
            self._mouse_listener.start()
        except Exception:
            # 半啟動回收：任一 listener 啟動失敗 → 停掉已建立的、重設狀態、再拋出
            for lst in (self._kb_listener, self._mouse_listener):
                if lst is not None:
                    try:
                        lst.stop()
                    except Exception:
                        pass
            self._kb_listener = None
            self._mouse_listener = None
            self._on_event = None
            raise

    def stop(self) -> None:
        if self._kb_listener is not None:
            self._kb_listener.stop()
            self._kb_listener = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None
        self._on_event = None

    # -- pynput callbacks → InputEvent --

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _emit(self, event: InputEvent) -> None:
        cb = self._on_event  # 快照：stop 後 listener 執行緒可能還送遲到事件
        if cb is not None:
            cb(event)

    def _canonical(self, key):
        """只對「字元鍵」做 canonical 正規化；特殊鍵（Key 物件）原樣回傳。

        canonical() 的用途僅是修正 Alt/Ctrl 按住時的字元變形，那只發生在字元鍵上。
        對 Key 物件呼叫它反而有害——pynput 會把任何帶 vk 的 Key 轉成純 vk 的
        KeyCode（keyboard/_base.py:762 `return KeyCode.from_vk(key.value.vk)`），
        而那種 KeyCode 的 .char 是 None，key_to_name 因此回 None，事件就被
        _on_press 靜默丟棄。Windows 上每個特殊鍵都有 vk，於是 home/方向鍵/
        delete/enter/tab/esc/F1-F20 全部錄不到（macOS 的 Key.value.vk 為 None，
        走 else 分支原樣回傳，所以只在 Windows 現形）。

        數字鍵盤同樣要跳過：Windows 的 canonical 對帶 scan code 的 KeyCode 會回傳
        KeyCode.from_char(char)（keyboard/_win32.py:395），vk 隨之遺失，NumLock 開著
        時 numpad 7 就退化成主鍵盤 7，兩顆實體鍵再也分不出來。

        修飾鍵的左右變體不靠 canonical 正規化——key_to_name 的 _MODIFIER_VARIANTS
        已負責把 ctrl_l/ctrl_r 折成 "ctrl"。
        """
        if not _is_char_key(key) or is_numpad(key):
            return key
        canon = getattr(self._kb_listener, "canonical", None)   # 測試 Spy 無此方法
        if canon is None:
            return key
        try:
            return canon(key)
        except Exception:
            return key

    def _on_press(self, key) -> None:
        name = key_to_name(self._canonical(key))
        if name is None:
            return  # 不支援的鍵（媒體鍵等）：略過，不進錄製
        self._emit(InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=self._now_ms(), key=name))

    def _on_release(self, key) -> None:
        name = key_to_name(self._canonical(key))
        if name is None:
            return
        self._emit(InputEvent(kind=EventKind.KEY_UP, timestamp_ms=self._now_ms(), key=name))

    def _on_move(self, x, y) -> None:
        self._emit(InputEvent(kind=EventKind.MOUSE_MOVE, timestamp_ms=self._now_ms(),
                              x=int(x), y=int(y)))

    def _on_click(self, x, y, button, pressed) -> None:
        mb = _BUTTON_NAMES.get(getattr(button, "name", None))
        if mb is None:
            return  # 左/中/右以外的按鍵：略過
        kind = EventKind.MOUSE_DOWN if pressed else EventKind.MOUSE_UP
        self._emit(InputEvent(kind=kind, timestamp_ms=self._now_ms(),
                              x=int(x), y=int(y), button=mb))

    def _on_scroll(self, x, y, dx, dy) -> None:
        self._emit(InputEvent(kind=EventKind.SCROLL, timestamp_ms=self._now_ms(),
                              x=int(x), y=int(y), dx=int(dx), dy=int(dy)))
