"""錄製/回放共用的全域控制守護：熱鍵與滑鼠角落 failsafe（spec §6/§7）。

- stop_key（預設 F10）按下 → stop_event.set()（緊急停止/放棄錄製）
- toggle_key（預設 F9）按下 → on_toggle()（錄製開始/停止；未提供則忽略）
- 滑鼠移進螢幕左上角 corner_size 範圍 → stop_event.set()（failsafe）
- is_control_event() 供錄製流程過濾控制鍵本身（自我過濾，不錄進腳本）

handle() 為公開方法：獨占 hook 時用 start() 直接掛上；錄製流程（cli.run_record）
用自己的 dispatcher 先呼叫 handle() 再決定是否轉送給 Recorder——同一個 hook
只能 start 一次，控制與轉送必須共用同一條事件流。
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from keyboard_executor.platforms.base import EventKind, InputEvent, InputHook

logger = logging.getLogger(__name__)


class SessionGuard:
    def __init__(self, hook: InputHook, stop_event: threading.Event,
                 on_toggle: Callable[[], None] | None = None,
                 toggle_key: str = "f9", stop_key: str = "f10",
                 corner_size: int = 5, corner_failsafe: bool = True):
        self._hook = hook
        self._stop_event = stop_event
        self._on_toggle = on_toggle
        self._toggle_key = toggle_key
        self._stop_key = stop_key
        self._corner_size = corner_size
        self._corner_failsafe = corner_failsafe

    def start(self) -> None:
        """獨占使用 hook 時的便利入口（回放路徑）。"""
        self._hook.start(self.handle)

    def stop(self) -> None:
        self._hook.stop()

    def handle(self, event: InputEvent) -> None:
        """處理單一事件的控制語義（hook callback；也可由外部 dispatcher 呼叫）。"""
        if event.kind is EventKind.KEY_DOWN:
            if event.key == self._stop_key:
                if not self._stop_event.is_set():
                    logger.info("偵測到緊急停止熱鍵（%s）→ 中止", self._stop_key)
                self._stop_event.set()
            elif event.key == self._toggle_key and self._on_toggle is not None:
                self._on_toggle()
        elif event.kind is EventKind.MOUSE_MOVE:
            if (self._corner_failsafe
                    and event.x is not None and event.y is not None
                    and 0 <= event.x <= self._corner_size
                    and 0 <= event.y <= self._corner_size):
                if not self._stop_event.is_set():
                    logger.info("偵測到緊急停止：滑鼠甩到螢幕左上角 → 中止")
                self._stop_event.set()

    def is_control_event(self, event: InputEvent) -> bool:
        """事件是否為控制鍵（toggle/stop）本身的 down/up——錄製時應過濾，不錄進腳本。"""
        return (event.kind in (EventKind.KEY_DOWN, EventKind.KEY_UP)
                and event.key in (self._toggle_key, self._stop_key))
