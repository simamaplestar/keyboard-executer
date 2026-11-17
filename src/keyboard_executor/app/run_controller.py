"""回放控制（純 Python，無 Qt import）：載入腳本、組 Player、產生 Worker job。

鏡射 cli.py 的 play 路徑：get_platform(game_input_mode=...)、storage/templates
注入、SessionGuard best-effort（F10/滑鼠甩左上角緊急停止；缺輸入監控權限時
只警告不阻斷）。stop() 設當前回放的 stop_event——Player 於下一個停止檢查點
安全中止。stop_key 由設定頁（Task 8）注入自訂值。
"""
from __future__ import annotations

import logging
import threading

from keyboard_executor.core.guard import SessionGuard
from keyboard_executor.core.player import Player
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.platforms.common.hook_pynput import PynputInputHook
from keyboard_executor.platforms.factory import get_platform

logger = logging.getLogger(__name__)


class RunController:
    def __init__(self, script_storage, templates, *,
                 get_platform=get_platform, player_factory=Player,
                 hook_factory=PynputInputHook, guard_factory=SessionGuard,
                 stop_key: str = "f10", corner_failsafe: bool = True,
                 chat_factory=None, sequence_factory=None):
        self._storage = script_storage
        self._templates = templates
        self._get_platform = get_platform
        self._player_factory = player_factory
        self._hook_factory = hook_factory
        self._guard_factory = guard_factory
        self._stop_key = stop_key
        self._corner_failsafe = corner_failsafe
        self._chat_factory = chat_factory
        self._sequence_factory = sequence_factory
        self._stop_event: threading.Event | None = None

    def build_job(self, name: str):
        """載入腳本並回傳 Worker job。載入失敗（不存在/損毀）就地拋
        ScriptValidationError——發生在 GUI 執行緒，呼叫端以日誌/訊息框顯示。"""
        script = self._storage.load(name)
        chat_enabled = script.settings.chat_reply is not None and script.settings.chat_reply.active
        sequence_enabled = script.settings.sequence_input is not None and script.settings.sequence_input.enabled
        if sequence_enabled and self._sequence_factory is None:
            raise ScriptValidationError("此執行環境未提供圖片順序輸入服務")
        if chat_enabled and not sequence_enabled and self._chat_factory is None:
            raise ScriptValidationError("此執行環境未提供 AI 自動回覆服務")
        stop_event = threading.Event()
        self._stop_event = stop_event

        def job(progress):
            platform = self._get_platform(
                game_input_mode=script.settings.game_input_mode,
                window_message_mode=script.settings.window_message_mode,
                scan_pulse_mode=script.settings.scan_pulse_mode)
            extra = {}
            guard = self._start_guard(stop_event)
            try:
                if sequence_enabled:
                    extra["on_action_boundary"] = self._sequence_factory(script, platform, stop_event, progress)
                elif chat_enabled:
                    extra["on_action_boundary"] = self._chat_factory(script, platform, stop_event, progress)
                player = self._player_factory(platform, storage=self._storage,
                                              templates=self._templates,
                                              stop_event=stop_event,
                                              on_step=progress, **extra)
                return player.play(script)
            finally:
                chat = extra.get("on_action_boundary")
                try:
                    if chat is not None and hasattr(chat, "close"):
                        chat.close()
                finally:
                    if guard is not None:
                        try:
                            guard.stop()
                        except Exception:
                            pass  # 守護收尾失敗不影響回放結果
        return job

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    def apply_settings(self, *, stop_key: str, get_platform,
                       corner_failsafe: bool = True) -> None:
        """就地更新下一次 build_job 會用到的設定；不影響進行中的回放
        （進行中的 job 已捕獲自己的 stop_event 與 platform）。"""
        self._stop_key = stop_key
        self._get_platform = get_platform
        self._corner_failsafe = corner_failsafe

    def _start_guard(self, stop_event):
        """best-effort 緊急停止（鏡射 cli._start_play_guard）。"""
        try:
            guard = self._guard_factory(self._hook_factory(), stop_event,
                                        stop_key=self._stop_key,
                                        corner_failsafe=self._corner_failsafe)
            guard.start()
            logger.info("緊急停止已啟用：熱鍵 %s，或滑鼠甩到螢幕左上角",
                        self._stop_key.upper())
            return guard
        except Exception:
            logger.warning("緊急停止熱鍵無法啟用（仍可用停止按鈕）", exc_info=True)
            return None
