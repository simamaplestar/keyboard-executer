import threading

from keyboard_executor.core.guard import SessionGuard
from keyboard_executor.platforms.base import EventKind, InputEvent
from tests.fakes import FakeInputHook


def key_down(key, ts=0):
    return InputEvent(kind=EventKind.KEY_DOWN, timestamp_ms=ts, key=key)


def key_up(key, ts=0):
    return InputEvent(kind=EventKind.KEY_UP, timestamp_ms=ts, key=key)


def mouse_move(x, y, ts=0):
    return InputEvent(kind=EventKind.MOUSE_MOVE, timestamp_ms=ts, x=x, y=y)


def make_guard(**kwargs):
    hook = FakeInputHook()
    stop = threading.Event()
    guard = SessionGuard(hook, stop, **kwargs)
    guard.start()
    return guard, hook, stop


def test_stop_key_down_sets_stop_event():
    _, hook, stop = make_guard()
    hook.push(key_down("f10"))
    assert stop.is_set()


def test_toggle_key_calls_on_toggle_per_key_down_only():
    toggles = []
    _, hook, stop = make_guard(on_toggle=lambda: toggles.append(1))
    hook.push(key_down("f9"))
    hook.push(key_up("f9"))
    hook.push(key_down("f9"))
    assert len(toggles) == 2  # 只有 down 觸發，up 不觸發
    assert not stop.is_set()


def test_toggle_without_callback_is_noop():
    _, hook, stop = make_guard()  # on_toggle=None
    hook.push(key_down("f9"))
    assert not stop.is_set()


def test_corner_move_triggers_failsafe():
    _, hook, stop = make_guard()
    hook.push(mouse_move(3, 4))
    assert stop.is_set()


def test_move_outside_corner_does_not_stop():
    _, hook, stop = make_guard()
    hook.push(mouse_move(6, 0))
    hook.push(mouse_move(0, 6))
    hook.push(mouse_move(100, 100))
    assert not stop.is_set()


def test_is_control_event_matches_toggle_and_stop_keys_only():
    guard, _, _ = make_guard()
    assert guard.is_control_event(key_down("f9")) is True
    assert guard.is_control_event(key_up("f9")) is True
    assert guard.is_control_event(key_down("f10")) is True
    assert guard.is_control_event(key_down("a")) is False
    assert guard.is_control_event(mouse_move(0, 0)) is False


def test_start_and_stop_delegate_to_hook():
    guard, hook, _ = make_guard()
    assert hook.started == 1
    guard.stop()
    assert hook.stopped == 1


def test_custom_keys():
    toggles = []
    guard, hook, stop = make_guard(on_toggle=lambda: toggles.append(1),
                                   toggle_key="f5", stop_key="f6")
    hook.push(key_down("f9"))  # 換鍵後 f9 不再是控制鍵
    hook.push(key_down("f5"))
    hook.push(key_down("f6"))
    assert len(toggles) == 1
    assert stop.is_set()
    assert guard.is_control_event(key_down("f5")) is True
    assert guard.is_control_event(key_down("f9")) is False


def test_corner_failsafe_off_ignores_corner_move():
    _, hook, stop = make_guard(corner_failsafe=False)
    hook.push(mouse_move(0, 0))
    assert not stop.is_set()          # 關閉時角落不觸發
