"""Schedule chat independently of player actions; deliver on the player only."""
from __future__ import annotations

import logging
import threading

from keyboard_executor.core.ai.provider import AiAborted
from keyboard_executor.core.chat_reply import ChatReplySession

logger = logging.getLogger(__name__)
_MAX_SUPERSEDE = 2
_QUICK_RECHECK_SEC = .3   # 偵測到新密語後多快再讀一次畫面


class BackgroundChatReplySession(ChatReplySession):
    """The GUI runtime. One lock owns observer/queue/scan state. OCR and AI
    futures only publish data; the monitor never activates a window or types.
    Action boundaries try the lock without waiting unless a reply is ready.
    """

    def __init__(self, *args, on_failure=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_failure = on_failure
        self._state_lock = threading.Lock()
        self._monitor = None
        self._queued_messages = []
        self._latest_image = None
        self._superseded = {}     # 對話 → 已備妥回覆因同一人新訊息重算的次數

    def __call__(self, script, win):
        try:
            return self._run_boundary(script, win)
        except Exception as exc:
            self._report_failure(exc)
            raise

    def _report_failure(self, exc):
        if self._on_failure is None or isinstance(exc, AiAborted) or self._stop.is_set():
            return
        try:
            self._on_failure(exc)
        except Exception:
            logger.warning("AI 自動回覆停止通知失敗")

    def close(self):
        try:
            super().close()
        except Exception as exc:
            self._report_failure(exc)
            raise

    def _run_boundary(self, script, win):
        if self._aborted() or not self._config.active:
            return
        if self._window is None:
            self._window = win
            self._notify("開始背景監看聊天，長按與延遲期間仍會檢查")
            self._monitor = threading.Thread(target=self._monitor_chat,
                                             name="chat-reply-monitor", daemon=True)
            self._monitor.start()
            return
        future = self._ai_result
        if win.handle != self._window.handle or future is None or not future.done():
            return
        try:
            prepared = future.result()
            needs_input = bool(prepared and prepared[1])
        except Exception:
            needs_input = False
        if not needs_input:
            # Empty/failed/cancelled results never justify pausing playback,
            # even when the monitor is consuming a frame or native OCR is slow.
            if self._state_lock.acquire(blocking=False):
                try:
                    if future is self._ai_result and not self._aborted():
                        self._take_ai_result(win)
                finally:
                    self._state_lock.release()
            return
        while not self._state_lock.acquire(timeout=.02):
            if self._aborted():
                return
        try:
            if self._ai_result is None or not self._ai_result.done() or self._aborted():
                return
            # A reply is ready and the current action has released its keys.
            # Drain any in-flight scan before the final delivery checks reuse
            # the OCR slot. Never overwrite/drop messages from that scan.
            while self._scan is not None and not self._scan.done():
                if self._stop.wait(.05) or self._aborted():
                    return
            self._poll_chat(win, start_scan=False)
            self._refresh_ai()
            if self._ai_result is not None and not self._aborted():
                if self._ai_result.done():
                    try:
                        prepared = self._ai_result.result()
                    except Exception:
                        prepared = None
                    if prepared and prepared[1]:
                        key = self._conversation_key(prepared[0][0])
                        if (self._may_supersede(key)
                                and any(self._conversation_key(m) == key
                                        for m in self._queued_messages)):
                            # Future completion precedes worker exit. A refresh
                            # may still be deferred; never send over queued updates.
                            return
                self._take_ai_result(win)
                if prepared and prepared[1] and self._ai_result is None:
                    # 已送出或放棄（不是又重新判斷）：這段對話重新開始計次。
                    self._superseded.pop(self._conversation_key(prepared[0][0]), None)
        finally:
            self._state_lock.release()

    def _may_supersede(self, key):
        # 對方一直打字時每則新訊息都重算會永遠送不出去；重算兩次後先送已備妥的回覆，
        # 新訊息留在佇列，送完再回。
        return self._superseded.get(key, 0) < _MAX_SUPERSEDE

    def _note_supersede(self, key):
        self._superseded[key] = self._superseded.get(key, 0) + 1

    def _monitor_chat(self):
        while not self._closed.is_set() and not self._stop.is_set():
            if self._state_lock.acquire(blocking=False):
                try:
                    if not self._aborted():
                        self._poll_chat(self._window)
                        self._refresh_ai()
                finally:
                    self._state_lock.release()
            # Only poll completion at this rate; captures still obey interval_sec
            # and at most one scan is in flight. close never joins native work.
            self._closed.wait(.02)

    def _on_chat_messages(self, image, candidates):
        self._notify(f"偵測到 {len(candidates)} 則新訊息，已加入 AI 待處理佇列")
        if any(m.channel == "whisper" for m in candidates):
            # 系統訊息洗版時密語幾秒就被擠出畫面：馬上再讀一次，確認姓名需要兩次相同讀法。
            self._next_check = min(self._next_check, self._clock() + _QUICK_RECHECK_SEC)
        self._defer_messages(image, candidates)

    def _defer_messages(self, image, candidates):
        if not candidates:
            return
        self._latest_image = image
        self._queued_messages = self._limit_pending(self._queued_messages + candidates)

    def _refresh_ai(self):
        if not self._queued_messages or self._aborted():
            return
        if self._ai_result is not None and not self._ai_result.done():
            return
        if ((self._pending is not None and self._pending.is_alive())
                or (self._prepare_worker is not None and self._prepare_worker.is_alive())):
            return
        if self._ai_result is not None:
            future = self._ai_result
            try:
                prepared = future.result()
                if prepared is not None and prepared[1]:
                    key = self._conversation_key(prepared[0][0])
                    if not any(self._conversation_key(m) == key for m in self._queued_messages):
                        return  # Another player cannot invalidate this ready reply.
                    if not self._may_supersede(key):
                        return  # 已重算多次：先送出這次回覆。
                    self._note_supersede(key)
                    self._queued_messages = self._limit_pending(prepared[0] + self._queued_messages)
            except Exception as exc:
                self._notify(f"本次未送出回覆，改為處理後續訊息：{exc}")
            self._ai_result = None
        candidates, self._queued_messages = self._queued_messages, []
        self._notify("開始處理玩家對話，背景產生 AI 回覆，腳本繼續執行")
        self._start_ai(self._latest_image, candidates)

    def suspend(self):
        with self._state_lock:
            super().suspend()
            self._superseded = {}
            self._queued_messages = []
            self._latest_image = None

    def resume(self):
        with self._state_lock:
            super().resume()
