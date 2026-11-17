from keyboard_executor.core.geometry import Point
from keyboard_executor.core.models import ActionType
from keyboard_executor.core.recorder import Recorder
from keyboard_executor.platforms.base import EventKind, InputEvent, MouseButton

ORIGIN = Point(100, 200)


def mouse_down(x, y, ts=0, button=MouseButton.LEFT):
    return InputEvent(kind=EventKind.MOUSE_DOWN, timestamp_ms=ts, x=x, y=y, button=button)


def mouse_up(x, y, ts=0, button=MouseButton.LEFT):
    return InputEvent(kind=EventKind.MOUSE_UP, timestamp_ms=ts, x=x, y=y, button=button)


def mouse_move(x, y, ts=0):
    return InputEvent(kind=EventKind.MOUSE_MOVE, timestamp_ms=ts, x=x, y=y)


def scroll(x, y, dx=0, dy=0, ts=0):
    return InputEvent(kind=EventKind.SCROLL, timestamp_ms=ts, x=x, y=y, dx=dx, dy=dy)


def record(events, mode="simplified"):
    recorder = Recorder(ORIGIN, mode=mode)
    for e in events:
        recorder.feed(e)
    return recorder.finish()


def test_down_up_without_movement_is_click_at_relative_coords():
    actions = record([mouse_down(150, 260, ts=0), mouse_up(150, 260, ts=30)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.MOUSE_CLICK, {"x": 50, "y": 60, "button": "left", "count": 1}),
    ]


def test_displacement_within_5px_still_click_uses_down_coords():
    actions = record([mouse_down(150, 260, ts=0), mouse_up(155, 264, ts=30)])
    assert actions[0].type is ActionType.MOUSE_CLICK
    assert (actions[0].params["x"], actions[0].params["y"]) == (50, 60)


def test_displacement_beyond_5px_becomes_drag():
    actions = record([mouse_down(150, 260, ts=0, button=MouseButton.RIGHT),
                      mouse_up(200, 300, ts=30, button=MouseButton.RIGHT)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.MOUSE_DRAG, {"from": [50, 60], "to": [100, 100], "button": "right"}),
    ]


def test_scroll_records_relative_position_and_deltas():
    actions = record([scroll(110, 220, dx=0, dy=-3)])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.SCROLL, {"x": 10, "y": 20, "dx": 0, "dy": -3}),
    ]


def test_simplified_mode_drops_mouse_moves():
    actions = record([mouse_move(110, 210, ts=0), mouse_move(120, 220, ts=200)])
    assert actions == []


def test_full_mode_samples_moves_every_100ms():
    actions = record([
        mouse_move(110, 210, ts=0),    # 第一個 move 保留
        mouse_move(111, 211, ts=50),   # 距上次保留 50ms < 100ms，丟棄
        mouse_move(120, 220, ts=120),  # 120ms >= 100ms，保留
        mouse_move(130, 230, ts=300),  # 180ms >= 100ms，保留
    ], mode="full")
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.MOUSE_MOVE, {"x": 10, "y": 10}),
        (ActionType.DELAY, {"ms": 120}),
        (ActionType.MOUSE_MOVE, {"x": 20, "y": 20}),
        (ActionType.DELAY, {"ms": 180}),
        (ActionType.MOUSE_MOVE, {"x": 30, "y": 30}),
    ]


def test_moves_during_drag_are_ignored_in_both_modes():
    for mode in ("simplified", "full"):
        actions = record([
            mouse_down(150, 260, ts=0),
            mouse_move(180, 280, ts=40),
            mouse_move(200, 300, ts=200),
            mouse_up(200, 300, ts=240),
        ], mode=mode)
        assert [a.type for a in actions] == [ActionType.MOUSE_DRAG]


def test_mouse_up_without_down_is_ignored():
    actions = record([mouse_up(150, 260, ts=0)])
    assert actions == []


def test_other_button_up_between_down_and_up_is_ignored():
    # 左鍵 down → 右鍵 up（不同鍵，應忽略且不清 pending）→ 左鍵 up（位移 0）→ 單一 click
    actions = record([
        mouse_down(150, 260, ts=0, button=MouseButton.LEFT),
        mouse_up(150, 260, ts=10, button=MouseButton.RIGHT),
        mouse_up(150, 260, ts=30, button=MouseButton.LEFT),
    ])
    assert [(a.type, a.params) for a in actions] == [
        (ActionType.MOUSE_CLICK, {"x": 50, "y": 60, "button": "left", "count": 1}),
    ]


def test_delay_inserted_between_clicks():
    actions = record([
        mouse_down(150, 260, ts=0), mouse_up(150, 260, ts=20),
        mouse_down(160, 270, ts=520), mouse_up(160, 270, ts=540),
    ])
    assert [a.type for a in actions] == [
        ActionType.MOUSE_CLICK, ActionType.DELAY, ActionType.MOUSE_CLICK,
    ]
    assert actions[1].params == {"ms": 520}
