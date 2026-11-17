import threading

import pytest

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import TAP_HOLD_MS, Player, PlayResult
from keyboard_executor.platforms.base import MouseButton, WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeWindowManager


def make_window(x=100, y=200, title="記事本"):
    return WindowInfo(handle=object(), title=title, app_name="Notepad",
                      x=x, y=y, width=800, height=600, is_active=False)


def make_platform(windows=None):
    backend = FakeInputBackend()
    manager = FakeWindowManager(windows if windows is not None else [make_window()])
    return Platform(input_backend=backend, window_manager=manager), backend, manager


def make_script(actions, settings=None):
    data = {
        "name": "測試",
        "target_window": {"title_pattern": "記事本"},
        "actions": actions,
    }
    if settings:
        data["settings"] = settings
    return script_from_dict(data)


def test_runs_keyboard_actions_in_order():
    platform, backend, manager = make_platform()
    script = make_script([
        {"type": "key_press", "key": "enter"},
        {"type": "key_combo", "keys": ["ctrl", "s"]},
        {"type": "text_input", "text": "哈囉"},
    ])
    result = Player(platform).play(script)
    assert result == PlayResult(ok=True, actions_run=3)
    assert backend.calls == [
        ("key_press", "enter", TAP_HOLD_MS),
        ("key_combo", ["ctrl", "s"]),
        ("type_text", "哈囉"),
    ]
    assert manager.activated  # 有先切前景
    assert backend.target_windows == [manager.windows[0]]


def test_key_press_tap_holds_minimum_duration_for_polled_input():
    # hold_ms=0 的點按仍要按住 TAP_HOLD_MS：輪詢式讀鍵（DirectInput/GetAsyncKeyState）
    # 的遊戲會在兩次輪詢間漏掉 0ms 的按下＋放開（同 key_combo 的 _COMBO_HOLD 理由）。
    platform, backend, _ = make_platform()
    result = Player(platform).play(
        make_script([{"type": "key_press", "key": "up"}]))
    assert result.ok
    assert backend.calls == [("key_press", "up", TAP_HOLD_MS)]


def test_mouse_coordinates_converted_to_absolute():
    platform, backend, _ = make_platform([make_window(x=100, y=200)])
    script = make_script([
        {"type": "mouse_click", "x": 10, "y": 20},
        {"type": "mouse_move", "x": 1, "y": 2},
        {"type": "mouse_drag", "from": [0, 0], "to": [5, 5]},
        {"type": "scroll", "x": 3, "y": 4, "dy": -2},
    ])
    result = Player(platform).play(script)
    assert result.ok
    assert backend.calls == [
        ("mouse_click", 110, 220, MouseButton.LEFT, 1),
        ("mouse_move", 101, 202),
        ("mouse_drag", 100, 200, 105, 205, MouseButton.LEFT),
        ("scroll", 103, 204, 0, -2),
    ]


def test_window_not_found_returns_error():
    platform, backend, _ = make_platform([])
    result = Player(platform).play(make_script([{"type": "key_press", "key": "a"}]))
    assert result.ok is False
    assert "找不到目標視窗" in result.error
    assert backend.calls == []


def test_window_retry_then_success():
    win = make_window()

    class LateWindowManager(FakeWindowManager):
        def __init__(self):
            super().__init__([])
            self.find_calls = 0

        def find_windows(self, title_pattern=None, app_name=None):
            self.find_calls += 1
            if self.find_calls >= 3:
                self.windows = [win]
            return super().find_windows(title_pattern, app_name)

    manager = LateWindowManager()
    backend = FakeInputBackend()
    platform = Platform(input_backend=backend, window_manager=manager)
    sleeps = []
    script = make_script([{"type": "key_press", "key": "a"}],
                         settings={"window_retry": 3, "window_retry_interval_ms": 500})
    result = Player(platform, sleep=sleeps.append).play(script)
    assert result.ok
    assert manager.find_calls == 3
    assert sleeps == [0.5, 0.5]  # 前兩次失敗各等一次


def test_activate_failure_returns_error():
    platform, _, manager = make_platform()
    manager.activate_result = False
    result = Player(platform).play(make_script([{"type": "key_press", "key": "a"}]))
    assert result.ok is False
    assert "前景" in result.error


def test_window_closed_mid_run_aborts_safely():
    platform, backend, manager = make_platform()

    class ClosingBackend(FakeInputBackend):
        def mouse_click(self, x, y, button=MouseButton.LEFT, count=1):
            super().mouse_click(x, y, button, count)
            manager.windows = []  # 第一個點擊後視窗被關閉

    backend = ClosingBackend()
    platform = Platform(input_backend=backend, window_manager=manager)
    script = make_script([
        {"type": "mouse_click", "x": 1, "y": 1},
        {"type": "mouse_click", "x": 2, "y": 2},
    ])
    result = Player(platform).play(script)
    assert result.ok is False
    assert "視窗已關閉" in result.error
    assert result.actions_run == 1  # 只完成第一個動作
    assert len([c for c in backend.calls if c[0] == "mouse_click"]) == 1


def test_pre_set_stop_event_aborts_immediately():
    platform, backend, manager = make_platform()
    stop = threading.Event()
    stop.set()
    result = Player(platform, stop_event=stop).play(
        make_script([{"type": "key_press", "key": "a"}]))
    assert result.ok is False
    assert "手動停止" in result.error
    assert backend.calls == []
    assert manager.activated == []  # 連視窗都不該去啟用


def test_stop_event_wins_over_window_not_found():
    platform, _, _ = make_platform([])  # 沒有任何視窗
    stop = threading.Event()
    stop.set()
    result = Player(platform, stop_event=stop).play(
        make_script([{"type": "key_press", "key": "a"}]))
    assert result.ok is False
    assert "手動停止" in result.error


def test_unexpected_backend_error_returns_result_not_raises():
    platform, _, manager = make_platform()

    class ExplodingBackend(FakeInputBackend):
        def key_press(self, key, hold_ms=0):
            raise ValueError("backend 內部錯誤")

    platform = Platform(input_backend=ExplodingBackend(), window_manager=manager)
    result = Player(platform).play(make_script([{"type": "key_press", "key": "a"}]))
    assert result.ok is False
    assert "未預期錯誤" in result.error


def test_key_press_hold_uses_key_down_wait_key_up():
    platform, backend, _ = make_platform()
    sleeps = []
    Player(platform, sleep=sleeps.append).play(
        make_script([{"type": "key_press", "key": "a", "hold_ms": 300}]))
    assert backend.calls == [("key_down", "a"), ("key_up", "a")]
    assert sleeps == [0.3]     # 以可中斷 _sleep 撐 hold（0.3 秒）


def test_key_press_hold_repeats_when_backend_requests_it():
    platform, backend, _ = make_platform()
    sleeps = []
    backend.key_repeat_interval = lambda _key: 0.03
    backend.key_repeat = lambda key: backend.calls.append(("key_repeat", key))

    Player(platform, sleep=sleeps.append).play(
        make_script([{"type": "key_press", "key": "up", "hold_ms": 100}]))

    assert backend.calls == [
        ("key_down", "up"),
        ("key_repeat", "up"),
        ("key_repeat", "up"),
        ("key_repeat", "up"),
        ("key_up", "up"),
    ]
    assert sleeps == pytest.approx([0.03, 0.03, 0.03, 0.01])


def test_key_press_hold_accounts_for_time_spent_inside_pulse():
    platform, backend, _ = make_platform()
    sleeps = []
    backend.key_repeat_interval = lambda _key: 0.018

    def pulse(key):
        backend.calls.append(("key_repeat", key))
        return 0.012

    backend.key_repeat = pulse
    Player(platform, sleep=sleeps.append).play(
        make_script([{"type": "key_press", "key": "up", "hold_ms": 100}]))

    assert backend.calls == [
        ("key_down", "up"),
        ("key_repeat", "up"),
        ("key_repeat", "up"),
        ("key_repeat", "up"),
        ("key_up", "up"),
    ]
    assert sleeps == pytest.approx([0.018, 0.018, 0.018, 0.01])


def test_key_press_hold_releases_key_and_aborts_on_stop():
    platform, backend, _ = make_platform()
    stop = threading.Event()

    def sleep_then_stop(seconds):
        stop.set()             # 模擬 hold 途中按下停止

    result = Player(platform, stop_event=stop, sleep=sleep_then_stop).play(
        make_script([{"type": "key_press", "key": "a", "hold_ms": 500},
                     {"type": "key_press", "key": "b"}]))
    assert backend.calls == [("key_down", "a"), ("key_up", "a")]  # a 放開、b 未送
    assert result.ok is False                                     # 停止後中止


def test_key_combo_hold_uses_combo_down_wait_up():
    platform, backend, _ = make_platform()
    sleeps = []
    Player(platform, sleep=sleeps.append).play(
        make_script([{"type": "key_combo", "keys": ["ctrl", "s"], "hold_ms": 300}]))
    assert backend.calls == [("key_down", "ctrl"), ("key_down", "s"),
                             ("key_up", "s"), ("key_up", "ctrl")]
    assert sleeps == [0.3]


def test_key_combo_no_hold_uses_key_combo():
    platform, backend, _ = make_platform()
    Player(platform).play(make_script([{"type": "key_combo", "keys": ["ctrl", "s"]}]))
    assert backend.calls == [("key_combo", ["ctrl", "s"])]


def test_key_combo_hold_releases_and_aborts_on_stop():
    platform, backend, _ = make_platform()
    stop = threading.Event()

    def sleep_then_stop(seconds):
        stop.set()             # 模擬 hold 途中按下停止

    result = Player(platform, stop_event=stop, sleep=sleep_then_stop).play(
        make_script([{"type": "key_combo", "keys": ["ctrl", "s"], "hold_ms": 500},
                     {"type": "key_press", "key": "b"}]))
    assert backend.calls == [("key_down", "ctrl"), ("key_down", "s"),
                             ("key_up", "s"), ("key_up", "ctrl")]   # 放開、b 未送
    assert result.ok is False                                       # 停止後中止


@pytest.mark.parametrize('keys', [['down', 'space'], ['space', 'down']])
def test_direction_combo_holds_arrow_before_and_after_other_key(keys):
    platform, backend, _ = make_platform()
    sleeps = []
    Player(platform, sleep=sleeps.append).play(
        make_script([{"type": "key_combo", "keys": keys}]))
    assert backend.calls == [("key_down", "down"), ("key_down", "space"),
                             ("key_up", "space"), ("key_up", "down")]
    assert sleeps == [0.1, TAP_HOLD_MS / 1000, 0.1]


def test_direction_combo_hold_applies_to_other_key_inside_arrow_hold():
    platform, backend, _ = make_platform()
    sleeps = []
    Player(platform, sleep=sleeps.append).play(
        make_script([{"type": "key_combo", "keys": ["right", "z"], "hold_ms": 2000}]))
    assert backend.calls == [("key_down", "right"), ("key_down", "z"),
                             ("key_up", "z"), ("key_up", "right")]
    assert sleeps == [0.1, 2.0, 0.1]


@pytest.mark.parametrize('keys', [['ctrl', 'left'], ['up', 'down']])
def test_text_shortcuts_and_arrow_only_combos_keep_plain_combo(keys):
    platform, backend, _ = make_platform()
    Player(platform).play(make_script([{"type": "key_combo", "keys": keys}]))
    assert backend.calls == [("key_combo", keys)]


def test_stop_during_arrow_lead_never_presses_other_key():
    platform, backend, _ = make_platform()
    stop = threading.Event()
    result = Player(platform, stop_event=stop, sleep=lambda s: stop.set()).play(
        make_script([{"type": "key_combo", "keys": ["down", "space"]},
                     {"type": "key_press", "key": "b"}]))
    assert backend.calls == [("key_down", "down"), ("key_up", "down")]   # b 未送
    assert result.ok is False
