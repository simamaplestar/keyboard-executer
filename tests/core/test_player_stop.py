import threading
import time

from keyboard_executor.core.models import script_from_dict
from keyboard_executor.core.player import Player
from keyboard_executor.platforms.base import WindowInfo
from keyboard_executor.platforms.factory import Platform
from tests.fakes import FakeInputBackend, FakeWindowManager


def make_platform():
    backend = FakeInputBackend()
    manager = FakeWindowManager([WindowInfo(handle=object(), title="記事本", app_name="App",
                                            x=0, y=0, width=100, height=100, is_active=False)])
    return Platform(input_backend=backend, window_manager=manager), backend


def make_script(actions):
    return script_from_dict({
        "name": "測試",
        "target_window": {"title_pattern": "記事本"},
        "actions": actions,
    })


def test_stop_event_interrupts_default_sleep_during_delay():
    platform, backend = make_platform()
    player = Player(platform)  # 不注入 sleep——用預設的可中斷等待
    script = make_script([
        {"type": "delay", "ms": 5000},
        {"type": "key_press", "key": "a"},
    ])
    timer = threading.Timer(0.05, player.stop_event.set)
    timer.start()
    t0 = time.monotonic()
    result = player.play(script)
    elapsed = time.monotonic() - t0
    timer.cancel()
    assert elapsed < 2.0  # 不等滿 5 秒（wait 提早返回）
    assert result.ok is False
    assert "已手動停止" in result.error
    assert backend.calls == []  # delay 後的 key_press 沒有執行


def test_default_sleep_waits_out_delay_when_not_stopped():
    platform, _ = make_platform()
    player = Player(platform)
    script = make_script([{"type": "delay", "ms": 50}])
    t0 = time.monotonic()
    result = player.play(script)
    elapsed = time.monotonic() - t0
    assert result.ok is True
    assert elapsed >= 0.04  # 沒被停止時要等好等滿
