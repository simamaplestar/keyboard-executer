import random
import threading

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeWindowManager


def make_window(title="記事本"):
    return WindowInfo(handle=object(), title=title, app_name="App",
                      x=0, y=0, width=100, height=100, is_active=False)


def make_platform():
    backend = FakeInputBackend()
    manager = FakeWindowManager([make_window()])
    return Platform(input_backend=backend, window_manager=manager), backend


def make_script(actions, settings=None, name="測試"):
    data = {"name": name, "target_window": {"title_pattern": "記事本"}, "actions": actions}
    if settings:
        data["settings"] = settings
    return script_from_dict(data)


def test_delay_scaled_by_speed():
    platform, _ = make_platform()
    sleeps = []
    script = make_script([{"type": "delay", "ms": 1000}], settings={"speed": 2.0})
    assert Player(platform, sleep=sleeps.append).play(script).ok
    assert sleeps == [0.5]  # 1000ms / 2.0 倍速


def test_delay_range_uses_rng():
    platform, _ = make_platform()
    sleeps = []
    script = make_script([{"type": "delay", "ms": [100, 200]}])
    Player(platform, sleep=sleeps.append, rng=random.Random(42)).play(script)
    expected = random.Random(42).randint(100, 200) / 1000
    assert sleeps == [expected]


def test_delay_jitter_deterministic_with_seeded_rng():
    platform, _ = make_platform()
    sleeps = []
    script = make_script([{"type": "delay", "ms": 1000}],
                         settings={"humanize_jitter_pct": 10})
    Player(platform, sleep=sleeps.append, rng=random.Random(7)).play(script)
    expected = 1000 * (1 + random.Random(7).uniform(-10, 10) / 100) / 1000
    assert sleeps == [expected]
    assert 0.9 <= sleeps[0] <= 1.1


def test_repeat_runs_actions_twice():
    platform, backend = make_platform()
    script = make_script([{"type": "key_press", "key": "a"}], settings={"repeat": 2})
    result = Player(platform).play(script)
    assert result.ok
    assert result.actions_run == 2
    assert len(backend.calls) == 2


def test_loop_count_runs_nested_actions():
    platform, backend = make_platform()
    script = make_script([
        {"type": "loop", "count": 3, "actions": [{"type": "key_press", "key": "a"}]},
    ])
    result = Player(platform).play(script)
    assert result.ok
    assert len([c for c in backend.calls if c[0] == "key_press"]) == 3
    # loop 本身 1 + 內部 3
    assert result.actions_run == 4


def test_infinite_loop_stopped_by_stop_event():
    platform, backend = make_platform()
    stop = threading.Event()

    class StopAfterFive(FakeInputBackend):
        def key_press(self, key, hold_ms=0):
            super().key_press(key, hold_ms)
            if len(self.calls) >= 5:
                stop.set()

    backend = StopAfterFive()
    platform = Platform(input_backend=backend, window_manager=platform.window_manager)
    script = make_script([
        {"type": "loop", "count": -1, "actions": [{"type": "key_press", "key": "a"}]},
    ])
    result = Player(platform, stop_event=stop).play(script)
    assert result.ok is False
    assert "手動停止" in result.error
    assert len(backend.calls) == 5


def test_infinite_repeat_stopped_by_stop_event():
    platform, backend = make_platform()
    stop = threading.Event()

    class StopAfterThree(FakeInputBackend):
        def key_press(self, key, hold_ms=0):
            super().key_press(key, hold_ms)
            if len(self.calls) >= 3:
                stop.set()

    backend = StopAfterThree()
    platform = Platform(input_backend=backend, window_manager=platform.window_manager)
    script = make_script([{"type": "key_press", "key": "a"}], settings={"repeat": -1})
    result = Player(platform, stop_event=stop).play(script)
    assert result.ok is False
    assert len(backend.calls) == 3


class DictStorage:
    """測試用：以 dict 模擬 ScriptStorage.load。"""

    def __init__(self, scripts):
        self._scripts = {s.name: s for s in scripts}

    def load(self, name):
        from keyboard_executor.core.models import ScriptValidationError
        if name not in self._scripts:
            raise ScriptValidationError(f"找不到腳本 {name!r}")
        return self._scripts[name]


def test_run_script_executes_sub_script():
    platform, backend = make_platform()
    sub = make_script([{"type": "text_input", "text": "子"}], name="子腳本")
    main = make_script([{"type": "run_script", "script_name": "子腳本"}], name="主")
    result = Player(platform, storage=DictStorage([sub])).play(main)
    assert result.ok
    assert ("type_text", "子") in backend.calls


def test_run_script_without_storage_aborts():
    platform, _ = make_platform()
    main = make_script([{"type": "run_script", "script_name": "x"}])
    result = Player(platform).play(main)
    assert result.ok is False
    assert "儲存來源" in result.error


def test_run_script_cycle_detected():
    platform, _ = make_platform()
    a = make_script([{"type": "run_script", "script_name": "b"}], name="a")
    b = make_script([{"type": "run_script", "script_name": "a"}], name="b")
    result = Player(platform, storage=DictStorage([a, b])).play(a)
    assert result.ok is False
    assert "循環" in result.error


def test_run_script_missing_sub_script_aborts_cleanly():
    platform, _ = make_platform()
    main = make_script([{"type": "run_script", "script_name": "不存在"}])
    result = Player(platform, storage=DictStorage([])).play(main)
    assert result.ok is False
    assert "找不到腳本" in result.error


def test_run_script_reactivates_parent_window():
    from keyboard_executor.platforms.base import WindowInfo
    from tests.fakes import FakeInputBackend, FakeWindowManager
    from keyboard_executor.platforms.factory import Platform

    win_a = WindowInfo(handle=object(), title="主視窗", app_name="A",
                       x=0, y=0, width=100, height=100, is_active=False)
    win_b = WindowInfo(handle=object(), title="子視窗", app_name="B",
                       x=0, y=0, width=100, height=100, is_active=False)
    manager = FakeWindowManager([win_a, win_b])
    backend = FakeInputBackend()
    platform = Platform(input_backend=backend, window_manager=manager)

    sub = script_from_dict({"name": "子", "target_window": {"title_pattern": "子視窗"},
                            "actions": [{"type": "text_input", "text": "b"}]})
    main = script_from_dict({"name": "主", "target_window": {"title_pattern": "主視窗"},
                             "actions": [{"type": "run_script", "script_name": "子"},
                                         {"type": "text_input", "text": "a"}]})
    result = Player(platform, storage=DictStorage([sub])).play(main)
    assert result.ok
    assert [w.title for w in manager.activated] == ["主視窗", "子視窗", "主視窗"]
    assert [w.title for w in backend.target_windows] == ["主視窗", "子視窗", "主視窗"]


def test_run_script_nesting_over_limit_aborts():
    platform, _ = make_platform()
    chain = []
    for i in range(10):
        actions = ([{"type": "run_script", "script_name": f"s{i + 1}"}]
                   if i < 9 else [{"type": "text_input", "text": "end"}])
        chain.append(make_script(actions, name=f"s{i}"))
    result = Player(platform, storage=DictStorage(chain)).play(chain[0])
    assert result.ok is False
    assert "巢狀超過" in result.error


def test_goto_jumps_to_same_level_action():
    # 段落結尾共用 #0 的判斷：goto 直接跳回，不用每段複製一份 minimap_goto。
    platform, _ = make_platform()
    sleeps = []
    script = make_script([{"type": "loop", "count": 1, "actions": [
        {"type": "delay", "ms": 10},
        {"type": "goto", "goto_index": 3},
        {"type": "delay", "ms": 999},          # 被跳過
        {"type": "delay", "ms": 30},
    ]}])
    assert Player(platform, sleep=sleeps.append).play(script).ok
    assert sleeps == [0.01, 0.03]


def test_goto_out_of_range_aborts():
    platform, _ = make_platform()
    result = Player(platform, sleep=lambda s: None).play(
        make_script([{"type": "goto", "goto_index": 5}]))
    assert not result.ok
