"""AI input pacing through real delivery and platform adapters, no desktop input."""
from dataclasses import replace
import sys
import time

import pytest

from keyboard_executor.core.models import action_from_dict
from keyboard_executor.platforms.win32.input import Win32InputBackend
from tests.core.test_chat_reply import make_session
from tests.platforms.test_win32_input import SpyKeyboard, SpyMouse, SpyPdi


def test_chat_waits_after_releasing_selection_and_after_typing_before_enter():
    session, _, win, backend, _, _, _ = make_session()
    times = {}
    backend.key_combo_up = lambda _: times.setdefault('selected', time.monotonic())
    backend.type_text_literal = lambda _: times.setdefault('typed', time.monotonic())
    backend.key_press = lambda *_: times.setdefault('entered', time.monotonic())
    try:
        session._send([action_from_dict(a) for a in (
            {'type': 'key_combo', 'keys': ['ctrl', 'a'], 'hold_ms': 100},
            {'type': 'text_input', 'text': '{reply}'},
            {'type': 'key_press', 'key': 'enter'},
        )], win, 'hi', 'Friend')   # 名字不再輸入，用回覆文字檢查間隔
        assert times['typed'] - times['selected'] >= .25
        assert times['entered'] - times['typed'] >= .25
    finally:
        session.close()


@pytest.mark.parametrize('game_mode', [False, True])
def test_chat_channel_click_is_held_long_enough_for_game_frame_poll(game_mode):
    session, _, win, _, _, _, _ = make_session()
    mouse, pdi = SpyMouse(), SpyPdi()
    pressed, observed = False, 0

    def press(*_args, **_kwargs):
        nonlocal pressed
        pressed = True

    def release(*_args, **_kwargs):
        nonlocal pressed
        pressed = False

    def instant_click(*_args, **_kwargs):
        press()
        release()

    def frame_poll(seconds):
        nonlocal observed
        if pressed and seconds >= .05:
            observed += 1

    mouse.press, mouse.release, mouse.click = press, release, instant_click
    pdi.mouseDown, pdi.mouseUp, pdi.click = press, release, instant_click
    backend = Win32InputBackend(game_input_mode=game_mode, pdi=pdi,
                                keyboard=SpyKeyboard(), mouse=mouse, sleep=frame_poll)
    # Use a real native-handle-shaped target for set_target_window, but all
    # low-level keyboard/mouse dependencies above are in-memory fakes.
    win = replace(win, handle=123)
    session._platform.window_manager.windows = [win]
    session._platform = replace(session._platform, input_backend=backend)
    try:
        session._send([action_from_dict({'type': 'mouse_click', 'x': 10, 'y': 10})], win, '', '')
        assert observed == 1, 'An instantaneous press/release is missed between game frames'
        assert not pressed, 'Click must release the held button'
    finally:
        session.close()


@pytest.mark.skipif(sys.platform != 'win32', reason='native pydirectinput contract')
def test_held_chat_click_releases_even_when_pointer_triggers_corner_failsafe(monkeypatch):
    import pydirectinput as pdi

    position, flags = [100, 100], []
    monkeypatch.setattr(pdi, 'FAILSAFE', True)
    monkeypatch.setattr(pdi, 'PAUSE', 0)
    monkeypatch.setattr(pdi, 'position', lambda: tuple(position))
    monkeypatch.setattr(pdi, 'moveTo', lambda x, y: position.__setitem__(slice(None), [x, y]))

    def send_input(count, pointer, size):
        flags.append(pointer.contents.ii.mi.dwFlags)
        return count

    monkeypatch.setattr(pdi, 'SendInput', send_input)

    def pause(seconds):
        if flags:  # Move into failsafe only once the synthetic button is down.
            position[:] = [0, 0]

    backend = Win32InputBackend(game_input_mode=True, pdi=pdi,
                                keyboard=SpyKeyboard(), mouse=SpyMouse(), sleep=pause)
    with pytest.raises(pdi.FailSafeException):
        backend.mouse_click_checked(100, 100, check=lambda: None, hold_ms=100)
    assert flags == [pdi.MOUSEEVENTF_LEFTDOWN, pdi.MOUSEEVENTF_LEFTUP]
