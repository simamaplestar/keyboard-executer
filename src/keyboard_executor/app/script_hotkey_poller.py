"""Windows 系統級腳本啟動熱鍵：背景輪詢 GetAsyncKeyState，多綁定版。

沿用 AsyncKeyStopPoller 的作法（讀 OS async 按鍵狀態表，不經焦點/hook，遊戲中亦常
有效），但同時監看多個「腳本 → 按鍵組合」綁定：某綁定的所有鍵同時按下的上升緣 →
on_trigger(腳本名)。若遊戲在核心層過濾鍵盤則此法亦無效（接受）。僅 Windows 使用。
"""
from __future__ import annotations

import logging
import threading
import time

from keyboard_executor.app.key_stop_poller import win_key_down

logger = logging.getLogger(__name__)


class ScriptHotkeyPoller:
    def __init__(self, on_trigger, *, key_down_fn=None, sleep=None,
                 poll_interval: float = 0.03):
        self._on_trigger = on_trigger          # callable(script_name: str)
        self._key_down_fn = key_down_fn or win_key_down
        self._sleep = sleep or time.sleep
        self._poll_interval = poll_interval
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self._bindings: list[tuple[str, tuple[int, ...]]] = []

    def start(self, bindings) -> bool:
        """bindings: Iterable[(script_name, [vk, ...])]；至少一個有效綁定才啟動並回 True。"""
        self._bindings = [(name, tuple(vks)) for name, vks in bindings if vks]
        if not self._bindings:
            return False
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_flag.set()
        t = self._thread
        # 從輪詢執行緒自己呼叫 stop() 時不能 join 自己（RuntimeError）；設旗標即可。
        if t is not None and t is not threading.current_thread():
            t.join(timeout=1.0)
            self._thread = None

    def _run(self) -> None:
        prev = {name: False for name, _ in self._bindings}
        while not self._stop_flag.is_set():
            for name, vks in self._bindings:
                try:
                    down = all(self._key_down_fn(vk) for vk in vks)
                except Exception:
                    logger.warning("腳本熱鍵輪詢讀取失敗", exc_info=True)
                    down = False
                if down and not prev.get(name, False):
                    try:
                        self._on_trigger(name)
                    except Exception:
                        logger.exception("腳本熱鍵觸發處理失敗")
                prev[name] = down
            self._sleep(self._poll_interval)
