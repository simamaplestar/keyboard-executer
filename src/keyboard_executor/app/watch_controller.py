"""監看控制（純 Python，無 Qt import）：載入啟用規則、組 RuleEngine job。

鏡射 cli.run_watch：共用 stop_event 以 player_factory 閉包穿透給規則觸發的
Player（stop_all/停止監看按鈕能中斷執行中的規則腳本）；on_fire/notifier/
on_error 全轉為 progress 記錄（kind=fire/notify/error）供 GUI 日誌。
監看完全獨立於緊急停止：不啟動任何輸入 hook / SessionGuard，只能由「停止監看」
按鈕或規則 stop_all 觸發停止（緊急停止只中止 run_controller 的回放）。
與 cli.run_watch 的差異：此處 notifier 另經 make_notifier 扇出到 Discord（webhook
來自 GUI 設定），cli 無此設定來源故不扇出。"""
from __future__ import annotations

import threading

from keyboard_executor.core.discord_notify import make_notifier
from keyboard_executor.core.models import ScriptValidationError
from keyboard_executor.core.player import Player
from keyboard_executor.core.rule_engine import RuleEngine
from keyboard_executor.platforms.factory import get_platform


class WatchController:
    def __init__(self, rule_storage, script_storage, templates, *,
                 get_platform=get_platform, engine_factory=RuleEngine,
                 player_factory=Player, discord_webhook_url: str = "",
                 notifier_factory=make_notifier, on_stop_all=None):
        self._rule_storage = rule_storage
        self._script_storage = script_storage
        self._templates = templates
        self._get_platform = get_platform
        self._engine_factory = engine_factory
        self._player_factory = player_factory
        self._discord_webhook_url = discord_webhook_url
        self._notifier_factory = notifier_factory
        self._on_stop_all = on_stop_all   # stop_all 觸發時另停執行中的腳本（run_controller）
        self._stop_event: threading.Event | None = None

    def build_job(self):
        """載入啟用規則並回傳 Worker job；沒有啟用規則就地拋
        ScriptValidationError（GUI 執行緒，日誌顯示）。"""
        rules = self._rule_storage.load_enabled()
        if not rules:
            raise ScriptValidationError("沒有啟用中的規則")
        stop_event = threading.Event()
        self._stop_event = stop_event

        def job(progress):
            platform = self._get_platform()

            def player_factory_with_stop(*args, **kwargs):
                return self._player_factory(*args, stop_event=stop_event, **kwargs)

            def base_notifier(message):
                progress({"kind": "notify", "message": message})

            engine = self._engine_factory(
                platform, storage=self._script_storage, templates=self._templates,
                notifier=self._notifier_factory(base_notifier,
                                                self._discord_webhook_url),
                on_fire=lambda name, ttype: progress(
                    {"kind": "fire", "rule": name, "trigger": ttype}),
                on_error=lambda name, message: progress(
                    {"kind": "error", "message": f"規則「{name}」：{message}"}),
                on_fire_done=lambda name: progress({"kind": "fire_done", "rule": name}),
                player_factory=player_factory_with_stop,
                stop_event=stop_event, on_stop_all=self._on_stop_all)
            engine.run(rules)
            return f"已停止監看（{len(rules)} 條規則）"
        return job

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    def apply_settings(self, *, get_platform, discord_webhook_url: str) -> None:
        """就地更新下一次 build_job 會用到的設定；不影響進行中的監看。"""
        self._get_platform = get_platform
        self._discord_webhook_url = discord_webhook_url
