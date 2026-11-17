"""Windows 系統級按鍵緊急停止：背景輪詢 GetAsyncKeyState 讀實體按鍵狀態。

遊戲（含反作弊）常擋掉低階鍵盤 hook（pynput）與 RegisterHotKey 的訊息投遞；
GetAsyncKeyState 讀的是 OS 的 async 按鍵狀態表，不經訊息佇列/使用者態 hook/焦點，
常在那些機制都失效時仍讀得到。偵測停止鍵「未按→按下」上升緣即呼叫 on_trigger。
若遊戲在核心層過濾鍵盤則此法亦無效（接受）。僅 Windows 使用。
"""
from __future__ import annotations

import logging
import threading
import time

from keyboard_executor.app.global_hotkey import vk_for_key

logger = logging.getLogger(__name__)


def win_key_down(vk: int) -> bool:
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


_win_key_down = win_key_down   # 既有引用（AsyncKeyStopPoller 預設）相容


class AsyncKeyStopPoller:
    def __init__(self, on_trigger, *, key_down_fn=None, sleep=None,
                 poll_interval: float = 0.03):
        self._on_trigger = on_trigger
        self._key_down_fn = key_down_fn or _win_key_down
        self._sleep = sleep or time.sleep
        self._poll_interval = poll_interval
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, key_name: str) -> bool:
        vk = vk_for_key(key_name)
        if vk is None:
            return False
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run, args=(vk,), daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_flag.set()
        t = self._thread
        # 從輪詢執行緒自己呼叫 stop()（例如 on_trigger 或注入的 sleep）時不能 join 自己
        # （會 RuntimeError）；設好停止旗標即可，執行緒會在下一輪 top 檢查時自行結束。
        if t is not None and t is not threading.current_thread():
            t.join(timeout=1.0)
            self._thread = None

    def _run(self, vk: int) -> None:
        prev = False
        while not self._stop_flag.is_set():
            try:
                down = bool(self._key_down_fn(vk))
            except Exception:
                logger.warning("按鍵緊急停止輪詢讀取失敗", exc_info=True)
                down = False
            if down and not prev:
                try:
                    self._on_trigger()
                except Exception:
                    logger.exception("按鍵緊急停止觸發處理失敗")
            prev = down
            self._sleep(self._poll_interval)
