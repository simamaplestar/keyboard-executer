"""定時技能：設定解析、序列化與播放時在動作之間按下。"""
import pytest

from keyboard_executor.core.models import (
    ScriptValidationError, TimedKey, script_from_dict, script_to_dict,
    timed_keys_from_text, timed_keys_to_text,
)
from keyboard_executor.core.player import Player
from tests.core.test_player_flow import make_platform, make_script


def test_text_format_round_trip():
    items = timed_keys_from_text("1:120, 2：180，ctrl:30:300")
    assert items == (TimedKey("1", 120.0), TimedKey("2", 180.0),
                     TimedKey("ctrl", 30.0, hold_ms=300))
    assert timed_keys_to_text(items) == "1:120, 2:180, ctrl:30:300"
    assert timed_keys_from_text("  ") == ()


@pytest.mark.parametrize("bad", ["1", "1:abc", "notakey:10", "1:0", "1:2:3:4"])
def test_text_format_errors_are_clear(bad):
    with pytest.raises(ScriptValidationError, match="定時技能|timed_keys"):
        timed_keys_from_text(bad)


def test_settings_round_trip_and_omitted_when_empty():
    data = {"name": "s", "target_window": {"app_name": "x"},
            "settings": {"timed_keys": [{"key": "1", "interval_sec": 120}]},
            "actions": [{"type": "delay", "ms": 0}]}
    script = script_from_dict(data)
    assert script.settings.timed_keys == (TimedKey("1", 120.0),)
    saved = script_to_dict(script)["settings"]["timed_keys"]
    assert saved == [{"key": "1", "interval_sec": 120, "hold_ms": 100, "wait_ms": 500}]
    plain = script_from_dict({**data, "settings": {}})
    assert "timed_keys" not in script_to_dict(plain)["settings"]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def test_timed_keys_fire_at_start_and_then_every_interval():
    platform, backend = make_platform()
    clock = Clock()
    script = make_script([{"type": "delay", "ms": 1000}] * 25,
                         settings={"timed_keys": [{"key": "1", "interval_sec": 10},
                                                  {"key": "2", "interval_sec": 100}]})
    result = Player(platform, sleep=clock.sleep, clock=clock).play(script)
    assert result.ok
    pressed = [c[1] for c in backend.calls if c[0] in ("key_press", "key_down")]
    # 開始各放一次；之後 1 鍵約每 10 秒（含放技能的等待）再放，2 鍵還沒到。
    assert pressed.count("2") == 1
    assert pressed.count("1") == 3
    assert pressed[:2] == ["1", "2"]


def test_timed_keys_not_counted_as_actions():
    platform, backend = make_platform()
    clock = Clock()
    script = make_script([{"type": "delay", "ms": 0}],
                         settings={"timed_keys": [{"key": "1", "interval_sec": 5}]})
    result = Player(platform, sleep=clock.sleep, clock=clock).play(script)
    assert result.ok and result.actions_run == 1
