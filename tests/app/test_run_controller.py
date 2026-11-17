import logging
import threading

import pytest

from keyboard_executor.app.run_controller import RunController
from keyboard_executor.core.models import ScriptValidationError, script_from_dict
from keyboard_executor.core.player import PlayResult
from keyboard_executor.storage.scripts import ScriptStorage
from tests.fakes import FakeInputHook


class SpyPlayer:
    last = None

    def __init__(self, platform, storage=None, templates=None, stop_event=None,
                 on_step=None):
        SpyPlayer.last = self
        self.platform = platform
        self.storage = storage
        self.templates = templates
        self.stop_event = stop_event
        self.on_step = on_step

    def play(self, script):
        self.played = script.name
        if self.on_step is not None:
            self.on_step({"kind": "step", "index": 0, "total": 1,
                          "type": "key_press", "label": "按鍵 a"})
        return PlayResult(ok=True, actions_run=1)


class SpyGuard:
    instances = []

    def __init__(self, hook, stop_event, on_toggle=None,
                 toggle_key="f9", stop_key="f10", corner_size=5,
                 corner_failsafe=True):
        self.stop_event = stop_event
        self.stop_key = stop_key
        self.corner_failsafe = corner_failsafe
        self.started = 0
        self.stopped = 0
        SpyGuard.instances.append(self)

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


def make_controller(tmp_path, *, game_mode=False, window_message_mode=False,
                    scan_pulse_mode=False,
                    guard_factory=SpyGuard,
                    stop_key="f10"):
    storage = ScriptStorage(tmp_path)
    data = {"name": "甲", "target_window": {"title_pattern": "記事本"},
            "actions": [{"type": "key_press", "key": "a"}]}
    if game_mode or window_message_mode or scan_pulse_mode:
        data["settings"] = {
            "game_input_mode": game_mode,
            "window_message_mode": window_message_mode,
            "scan_pulse_mode": scan_pulse_mode,
        }
    storage.save(script_from_dict(data))
    captured = {}

    def fake_get_platform(**kwargs):
        captured.update(kwargs)
        return object()

    loader = object()
    controller = RunController(storage, loader, get_platform=fake_get_platform,
                               player_factory=SpyPlayer,
                               hook_factory=FakeInputHook,
                               guard_factory=guard_factory, stop_key=stop_key)
    return controller, storage, loader, captured


def test_build_job_wires_player_dependencies_and_forwards_progress(tmp_path):
    controller, storage, loader, _ = make_controller(tmp_path)
    records = []
    job = controller.build_job("甲")
    result = job(records.append)
    assert result == PlayResult(ok=True, actions_run=1)
    player = SpyPlayer.last
    assert player.storage is storage and player.templates is loader
    assert player.stop_event is not None and not player.stop_event.is_set()
    assert records == [{"kind": "step", "index": 0, "total": 1,
                        "type": "key_press", "label": "按鍵 a"}]


def test_build_job_missing_script_raises(tmp_path):
    controller, *_ = make_controller(tmp_path)
    with pytest.raises(ScriptValidationError, match="找不到腳本"):
        controller.build_job("不存在")


def test_chat_enabled_requires_service_factory_before_start(tmp_path):
    from tests.core.test_chat_reply_config import config_data, script_data
    controller, storage, *_ = make_controller(tmp_path)
    storage.save(script_from_dict(script_data(config_data())))
    with pytest.raises(ScriptValidationError, match="AI"):
        controller.build_job("聊天")


def test_both_chat_channels_disabled_do_not_require_service_factory(tmp_path):
    from tests.core.test_chat_reply_config import script_data
    controller, storage, *_ = make_controller(tmp_path)
    storage.save(script_from_dict(script_data({"enabled": True, "reply_map": False,
                                               "reply_whisper": False})))
    assert controller.build_job("聊天")(lambda _: None).ok


def test_run_controller_inserts_chat_without_restarting_script(tmp_path):
    from tests.core.test_chat_reply_config import config_data, script_data
    from tests.core.test_player_flow import make_platform
    platform, backend = make_platform()
    storage = ScriptStorage(tmp_path)
    data = script_data(config_data())
    data["target_window"]["title_pattern"] = "記事本"
    data["actions"] = [{"type": "key_press", "key": "a"},
                       {"type": "key_press", "key": "b"}]
    storage.save(script_from_dict(data))

    def chat_factory(script, actual_platform, stop, progress):
        assert actual_platform is platform

        def boundary(*_):
            if backend.calls:
                backend.type_text("回覆")
        return boundary

    controller = RunController(storage, None, get_platform=lambda **_: platform,
                               hook_factory=FakeInputHook, guard_factory=SpyGuard,
                               chat_factory=chat_factory)
    assert controller.build_job("聊天")(lambda _: None).ok
    assert [c[1] for c in backend.calls] == ["a", "回覆", "b"]


def test_sequence_factory_failure_stops_guard_and_never_plays(tmp_path):
    from tests.core.test_sequence_input_config import script_data
    controller, storage, *_ = make_controller(tmp_path)
    storage.save(script_from_dict(script_data()))
    def factory(*args):
        assert SpyGuard.instances[-1].started == 1
        raise ScriptValidationError("preflight failed")
    controller._sequence_factory = factory
    with pytest.raises(ScriptValidationError, match="preflight"):
        controller.build_job("順序輸入")(lambda _: None)
    assert SpyGuard.instances[-1].stopped == 1


def test_failing_runtime_close_still_stops_guard(tmp_path):
    from tests.core.test_sequence_input_config import script_data
    controller, storage, *_ = make_controller(tmp_path)
    storage.save(script_from_dict(script_data()))
    class Runtime:
        def close(self): raise RuntimeError("close failed")
    class Player:
        def __init__(self, *a, **kw): pass
        def play(self, script): return PlayResult(ok=True, actions_run=0)
    controller._sequence_factory = lambda *args: Runtime()
    controller._player_factory = Player
    with pytest.raises(RuntimeError, match="close failed"):
        controller.build_job("順序輸入")(lambda _: None)
    assert SpyGuard.instances[-1].stopped == 1


def test_stop_sets_current_stop_event(tmp_path):
    controller, *_ = make_controller(tmp_path)
    job = controller.build_job("甲")
    job(lambda r: None)
    controller.stop()
    assert SpyPlayer.last.stop_event.is_set()


@pytest.mark.parametrize("fail", [False, True])
def test_chat_service_is_closed_when_play_finishes_or_fails(tmp_path, fail):
    from tests.core.test_chat_reply_config import config_data, script_data
    controller, storage, *_ = make_controller(tmp_path)
    storage.save(script_from_dict(script_data(config_data())))
    closed = []

    class Chat:
        def __call__(self, *_):
            pass

        def close(self):
            closed.append(True)

    class Player:
        def __init__(self, *_, **__):
            pass

        def play(self, _):
            if fail:
                raise RuntimeError("player failed")
            return PlayResult(ok=True, actions_run=1)

    controller._chat_factory = lambda *_: Chat()
    controller._player_factory = Player
    if fail:
        with pytest.raises(RuntimeError, match="player failed"):
            controller.build_job("聊天")(lambda _: None)
    else:
        assert controller.build_job("聊天")(lambda _: None).ok
    assert closed == [True]


def test_game_input_mode_passed_to_get_platform(tmp_path):
    controller, _, _, captured = make_controller(tmp_path, game_mode=True)
    controller.build_job("甲")(lambda r: None)
    assert captured == {"game_input_mode": True, "window_message_mode": False,
                        "scan_pulse_mode": False}


def test_window_message_mode_passed_to_get_platform(tmp_path):
    controller, _, _, captured = make_controller(tmp_path, window_message_mode=True)
    controller.build_job("甲")(lambda r: None)
    assert captured == {"game_input_mode": False, "window_message_mode": True,
                        "scan_pulse_mode": False}


def test_scan_pulse_mode_passed_to_get_platform(tmp_path):
    controller, _, _, captured = make_controller(tmp_path, scan_pulse_mode=True)
    controller.build_job("甲")(lambda r: None)
    assert captured == {"game_input_mode": False, "window_message_mode": False,
                        "scan_pulse_mode": True}


def test_guard_best_effort_started_stopped_and_failure_ignored(tmp_path, caplog):
    SpyGuard.instances = []
    controller, *_ = make_controller(tmp_path, stop_key="f8")
    controller.build_job("甲")(lambda r: None)
    guard = SpyGuard.instances[-1]
    assert guard.started == 1 and guard.stopped == 1
    assert guard.stop_key == "f8"                       # 設定頁自訂熱鍵的掛點
    assert guard.stop_event is SpyPlayer.last.stop_event  # 與 Player 共用同一顆

    def exploding_guard(*a, **k):
        raise RuntimeError("缺輸入監控權限")

    controller2, *_ = make_controller(tmp_path, guard_factory=exploding_guard)
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        result = controller2.build_job("甲")(lambda r: None)
    assert result.ok                                     # 守護失敗不阻斷回放
    assert "緊急停止熱鍵無法啟用" in caplog.text


def test_apply_settings_takes_effect_on_next_build_job(tmp_path):
    controller, _storage, _loader, _captured = make_controller(tmp_path, stop_key="f10")
    marker = object()
    plat_calls = []
    controller.apply_settings(
        stop_key="f8",
        get_platform=lambda **k: (plat_calls.append(True), marker)[1])
    controller.build_job("甲")(lambda r: None)
    assert SpyGuard.instances[-1].stop_key == "f8"     # 新 stop_key 生效
    assert SpyPlayer.last.platform is marker           # 用了新的 get_platform
    assert plat_calls                                  # 新 get_platform 被呼叫


def test_run_controller_passes_corner_failsafe_to_guard(tmp_path):
    captured = {}

    class FakeGuard:
        def __init__(self, hook, stop_event, *, stop_key="f10", corner_failsafe=True):
            captured["corner_failsafe"] = corner_failsafe

        def start(self):
            pass

        def stop(self):
            pass

    controller = RunController(object(), object(), guard_factory=FakeGuard,
                               hook_factory=lambda: object(), corner_failsafe=False)
    controller._start_guard(threading.Event())
    assert captured["corner_failsafe"] is False
