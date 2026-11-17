from keyboard_executor.core.ai_demo.timeline import (
    DemoEventLog, KeyHold, MouseAct, format_timeline,
)
from keyboard_executor.core.geometry import Point
from keyboard_executor.platforms.base import EventKind, InputEvent, MouseButton


def key(kind, name, t):
    return InputEvent(kind=kind, timestamp_ms=t, key=name)


def mouse(kind, x, y, t, button=MouseButton.LEFT):
    return InputEvent(kind=kind, timestamp_ms=t, x=x, y=y, button=button)


def make_log():
    log = DemoEventLog(Point(100, 50))
    log.start(10_000)
    return log


def test_hold_interval_from_down_up():
    log = make_log()
    log.feed(key(EventKind.KEY_DOWN, "right", 11_200))
    log.feed(key(EventKind.KEY_UP, "right", 13_850))
    holds, acts = log.finish()
    assert holds == [KeyHold("right", 1200, 3850)]
    assert acts == []


def test_autorepeat_down_ignored():
    log = make_log()
    for t in (11_000, 11_030, 11_060):
        log.feed(key(EventKind.KEY_DOWN, "x", t))
    log.feed(key(EventKind.KEY_UP, "x", 11_500))
    holds, _ = log.finish()
    assert holds == [KeyHold("x", 1000, 1500)]


def test_unreleased_key_closed_at_finish():
    log = make_log()
    log.feed(key(EventKind.KEY_DOWN, "a", 11_000))
    log.feed(key(EventKind.KEY_DOWN, "b", 12_000))
    log.feed(key(EventKind.KEY_UP, "b", 12_400))
    holds, _ = log.finish()
    assert KeyHold("a", 1000, 2400) in holds


def test_mouse_click_vs_drag():
    log = make_log()
    log.feed(mouse(EventKind.MOUSE_DOWN, 150, 80, 11_000))
    log.feed(mouse(EventKind.MOUSE_UP, 153, 82, 11_100))
    log.feed(mouse(EventKind.MOUSE_DOWN, 150, 80, 12_000))
    log.feed(mouse(EventKind.MOUSE_UP, 250, 180, 12_300))
    _, acts = log.finish()
    assert acts == [MouseAct("click", 1000, 50, 30, "left"),
                    MouseAct("drag", 2000, 50, 30, "left", to=(150, 130))]


def test_scroll_recorded():
    log = make_log()
    log.feed(InputEvent(kind=EventKind.SCROLL, timestamp_ms=11_000, x=110, y=60, dy=-1))
    _, acts = log.finish()
    assert acts == [MouseAct("scroll", 1000, 10, 10, dy=-1)]


def test_event_times_include_key_downs_and_clicks():
    log = make_log()
    log.feed(key(EventKind.KEY_DOWN, "a", 11_000))
    log.feed(key(EventKind.KEY_UP, "a", 11_100))
    log.feed(mouse(EventKind.MOUSE_DOWN, 150, 80, 12_000))
    log.feed(mouse(EventKind.MOUSE_UP, 150, 80, 12_050))
    assert log.event_times_ms() == [1000, 2000]


def test_start_defaults_to_first_event():
    log = DemoEventLog(Point(0, 0))
    log.feed(key(EventKind.KEY_DOWN, "a", 5_000))
    log.feed(key(EventKind.KEY_UP, "a", 5_400))
    holds, _ = log.finish()
    assert holds == [KeyHold("a", 0, 400)]


def test_format_timeline_lines():
    holds = [KeyHold("right", 1200, 3850)]
    acts = [MouseAct("click", 500, 50, 30, "left")]
    dots = [(0, (100.0, 40.0)), (500, None), (1000, (112.0, 48.0))]
    frames = [(0, "D1"), (500, "D2"), (1000, "D3")]
    text = format_timeline(holds, acts, dots, frames)
    lines = text.splitlines()
    assert lines[0].startswith("0.50s 點擊 left (50,30)")
    assert "[D2]" in lines[0]
    assert "黃點(?)" in lines[0]
    assert "1.20s–3.85s 按住 right（2.65s）" in lines[1]
    assert "[D3]" in lines[1]
    assert "黃點(112,48)" in lines[1]
