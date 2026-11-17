import pytest

from keyboard_executor.app.watch_controller import WatchController
from keyboard_executor.core.models import ScriptValidationError, rule_from_dict
from keyboard_executor.storage.rules import RuleStorage


class SpyEngine:
    last = None

    def __init__(self, platform, storage=None, templates=None, notifier=None,
                 on_fire=None, on_error=None, player_factory=None, stop_event=None,
                 on_stop_all=None, on_fire_done=None):
        SpyEngine.last = self
        self.on_fire_done = on_fire_done
        self.notifier = notifier
        self.on_fire = on_fire
        self.on_error = on_error
        self.player_factory = player_factory
        self.stop_event = stop_event
        self.on_stop_all = on_stop_all
        self.ran = None

    def run(self, rules):
        self.ran = [r.name for r in rules]


def make_rule_storage(tmp_path):
    storage = RuleStorage(tmp_path)
    for name, enabled in (("開", True), ("關", False)):
        storage.save(rule_from_dict({
            "name": name, "target_window": {"title_pattern": "遊戲"},
            "condition": {"type": "text", "pattern": "x"},
            "trigger": {"type": "notify", "message": "y"}, "enabled": enabled}))
    return storage


def make_controller(tmp_path, *, player_factory=None, on_stop_all=None):
    return WatchController(
        make_rule_storage(tmp_path), object(), object(),
        get_platform=lambda **k: object(), engine_factory=SpyEngine,
        player_factory=player_factory or (lambda *a, **k: object()),
        on_stop_all=on_stop_all)


def test_build_job_runs_engine_with_enabled_rules_only(tmp_path):
    controller = make_controller(tmp_path)
    result = controller.build_job()(lambda r: None)
    assert SpyEngine.last.ran == ["開"]
    assert result == "已停止監看（1 條規則）"


def test_build_job_no_enabled_rules_raises(tmp_path):
    controller = WatchController(RuleStorage(tmp_path), object(), object(),
                                 engine_factory=SpyEngine)
    with pytest.raises(ScriptValidationError, match="沒有啟用中的規則"):
        controller.build_job()


def test_on_fire_and_notifier_become_progress_records(tmp_path):
    controller = make_controller(tmp_path)
    records = []
    controller.build_job()(records.append)
    engine = SpyEngine.last
    engine.on_fire("斷線", "run_script")
    engine.notifier("斷線了")
    assert records == [
        {"kind": "fire", "rule": "斷線", "trigger": "run_script"},
        {"kind": "notify", "message": "斷線了"}]


def test_on_error_becomes_error_record_with_rule_name(tmp_path):
    controller = make_controller(tmp_path)
    records = []
    controller.build_job()(records.append)
    SpyEngine.last.on_error("監控", "本輪擷取失敗")
    assert records == [{"kind": "error", "message": "規則「監控」：本輪擷取失敗"}]


def test_stop_sets_shared_stop_event_used_by_player_factory(tmp_path):
    captured = {}

    def spy_player_factory(*args, **kwargs):
        captured.update(kwargs)
        return object()

    controller = make_controller(tmp_path, player_factory=spy_player_factory)
    controller.build_job()(lambda r: None)
    engine = SpyEngine.last
    engine.player_factory(object(), storage=None)   # 模擬規則觸發 run_script 建 Player
    assert captured["stop_event"] is engine.stop_event
    assert not engine.stop_event.is_set()
    controller.stop()
    assert engine.stop_event.is_set()


def test_build_job_wires_webhook_into_notifier_factory(tmp_path):
    captured = {}

    def fake_notifier_factory(base, webhook):
        captured["base"] = base
        captured["webhook"] = webhook
        return "SPY_NOTIFIER"

    controller = WatchController(
        make_rule_storage(tmp_path), object(), object(),
        get_platform=lambda **k: object(), engine_factory=SpyEngine,
        player_factory=lambda *a, **k: object(),
        discord_webhook_url="https://discord.com/api/webhooks/1/abc",
        notifier_factory=fake_notifier_factory)
    records = []
    controller.build_job()(records.append)
    assert captured["webhook"] == "https://discord.com/api/webhooks/1/abc"
    assert SpyEngine.last.notifier == "SPY_NOTIFIER"     # 引擎拿到扇出後的 notifier
    captured["base"]("嗨")                                # base 仍把 notify 轉 progress
    assert records == [{"kind": "notify", "message": "嗨"}]


def test_build_job_passes_on_stop_all_to_engine(tmp_path):
    # WatchController 須把 on_stop_all 透傳給引擎，讓 stop_all 觸發時能停掉
    # 執行中的腳本（run_controller）。
    called = []
    controller = make_controller(tmp_path, on_stop_all=lambda: called.append(True))
    controller.build_job()(lambda r: None)
    assert SpyEngine.last.on_stop_all is not None
    SpyEngine.last.on_stop_all()
    assert called == [True]


def test_apply_settings_takes_effect_on_next_build_job(tmp_path):
    captured = {}

    def fake_notifier_factory(base, webhook):
        captured["webhook"] = webhook
        return base

    plat_calls = []
    controller = WatchController(
        make_rule_storage(tmp_path), object(), object(),
        get_platform=lambda **k: object(), engine_factory=SpyEngine,
        player_factory=lambda *a, **k: object(),
        discord_webhook_url="https://discord.com/api/webhooks/1/old",
        notifier_factory=fake_notifier_factory)
    controller.apply_settings(
        get_platform=lambda **k: (plat_calls.append(True), object())[1],
        discord_webhook_url="https://discord.com/api/webhooks/1/new")
    controller.build_job()(lambda r: None)
    assert captured["webhook"] == "https://discord.com/api/webhooks/1/new"  # 新 webhook
    assert plat_calls                                                    # 新 get_platform 被呼叫


def test_on_fire_done_becomes_progress_record(tmp_path):
    controller = make_controller(tmp_path)
    records = []
    controller.build_job()(records.append)
    SpyEngine.last.on_fire_done("測謊")
    assert records == [{"kind": "fire_done", "rule": "測謊"}]
