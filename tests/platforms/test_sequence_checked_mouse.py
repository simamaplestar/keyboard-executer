import pytest
from pynput.mouse import Button

from keyboard_executor.platforms.common.input_pynput import PynputInputBackend
from keyboard_executor.platforms.win32.input import Win32InputBackend
from tests.platforms.test_input_pynput import SpyKeyboard, SpyMouse
from tests.platforms.test_win32_input import SpyPdi


class Interrupted(Exception):
    pass


@pytest.mark.parametrize('game', [False, True])
def test_drag_release_on_pause_during_held_settle(game):
    mouse, pdi = SpyMouse(), SpyPdi()
    paused, spans = [False], []
    def sleep(seconds):
        spans.append(seconds)
        held = any(op[0] == ('mouseDown' if game else 'press') for op in (pdi.ops if game else mouse.ops))
        if held:
            paused[0] = True
    def check():
        if paused[0]:
            raise Interrupted()
    backend = Win32InputBackend(game_input_mode=game, pdi=pdi, keyboard=SpyKeyboard(), mouse=mouse, sleep=sleep)
    with pytest.raises(Interrupted):
        backend.mouse_drag_checked(1, 2, 3, 4, check=check)
    ops = pdi.ops if game else mouse.ops
    assert ops[-1][0] == ('mouseUp' if game else 'release')
    assert not any(op == ('moveTo', 3, 4) or op == ('move', (3, 4)) for op in ops)
    assert max(spans) <= .02


def test_scroll_pause_during_settle_never_dispatches_wheel():
    mouse, paused = SpyMouse(), [False]
    backend = PynputInputBackend(keyboard=SpyKeyboard(), mouse=mouse,
                                 sleep=lambda _: paused.__setitem__(0, True))
    def check():
        if paused[0]:
            raise Interrupted()
    with pytest.raises(Interrupted):
        backend.scroll_checked(1, 2, 0, -1, check=check)
    assert mouse.ops == [('move', (1, 2))]
