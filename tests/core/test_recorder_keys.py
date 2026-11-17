import pytest

from keyboard_executor.core.geometry import Point
from keyboard_executor.core.models import ActionType, action_from_dict, action_to_dict
from keyboard_executor.core.recorder import Recorder
from keyboard_executor.platforms.base import EventKind, InputEvent


def key_down(key, ts=0):
    return InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=ts, key=key)


def key_up(key, ts=0):
    return InputEvent(kind=EventKind.KEY_UP, timestamp_ms=ts, key=key)


def record(events, mode="simplified"):
    recorder = Recorder(Point(0, 0), mode=mode)
    for e in events:
        recorder.feed(e)
    return recorder.finish()


def test_plain_typing_becomes_key_presses():
    actions = record([key_down("h", 0), key_up("h", 10), key_down("i", 20), key_up("i", 30)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.KEY_PRESS, {"key": "h", "hold_ms": 0}),
        (ActionType.KEY_PRESS, {"key": "i", "hold_ms": 0}),
    ]


def test_ctrl_hold_plus_s_becomes_combo():
    actions = record([key_down("ctrl", 0), key_down("s", 30),
                      key_up("s", 40), key_up("ctrl", 45)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.KEY_COMBO, {"keys": ["ctrl", "s"], "hold_ms": 0}),
    ]


def test_modifier_order_is_fixed_ctrl_shift_alt_cmd():
    actions = record([key_down("shift", 0), key_down("ctrl", 10), key_down("a", 20)])
    assert actions[0].params == {"keys": ["ctrl", "shift", "a"], "hold_ms": 0}


def test_multiple_keys_under_held_modifier_each_become_combo():
    actions = record([
        key_down("ctrl", 0),
        key_down("a", 10), key_up("a", 15),
        key_down("b", 30), key_up("b", 35),
        key_up("ctrl", 40),
    ])
    assert [a.params for a in actions] == [
        {"keys": ["ctrl", "a"], "hold_ms": 0},
        {"keys": ["ctrl", "b"], "hold_ms": 0},
    ]


def test_released_modifier_no_longer_combines():
    actions = record([key_down("ctrl", 0), key_up("ctrl", 10), key_down("a", 20)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.KEY_PRESS, {"key": "a", "hold_ms": 0}),
    ]


def test_gap_of_50ms_or_more_inserts_delay():
    actions = record([key_down("a", 0), key_down("b", 300)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.KEY_PRESS, {"key": "a", "hold_ms": 0}),
        (ActionType.DELAY, {"ms": 300}),
        (ActionType.KEY_PRESS, {"key": "b", "hold_ms": 0}),
    ]


def test_gap_under_50ms_has_no_delay():
    actions = record([key_down("a", 0), key_down("b", 30)])
    assert [a.type for a in actions] == [ActionType.KEY_PRESS, ActionType.KEY_PRESS]


def test_delay_at_exact_threshold_50ms_inserted():
    actions = record([key_down("a", 0), key_down("b", 50)])
    assert [a.type for a in actions] == [ActionType.KEY_PRESS, ActionType.DELAY, ActionType.KEY_PRESS]


def test_no_delay_before_first_action():
    actions = record([key_down("a", 99999)])
    assert [a.type for a in actions] == [ActionType.KEY_PRESS]


def test_recorded_actions_round_trip_through_models():
    actions = record([key_down("ctrl", 0), key_down("s", 10), key_down("a", 200)])
    assert len(actions) == 3  # combo, delay(190), combo
    for action in actions:
        assert action_from_dict(action_to_dict(action)) == action


def test_invalid_mode_raises_in_chinese():
    with pytest.raises(ValueError, match="未知的錄製模式"):
        Recorder(Point(0, 0), mode="fancy")
