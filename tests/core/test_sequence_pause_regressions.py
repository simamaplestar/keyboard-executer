from dataclasses import replace
from types import SimpleNamespace

import pytest

from keyboard_executor.core.visual_intervention import VisualIntervention
from keyboard_executor.platforms.base import TextBox
from tests.core.test_player_sequence_pause import scenario
from tests.core.test_sequence_panel_helpers import make_panel_watcher, PROMPT
from tests.fakes import FakeScreenCapture, FakeOcrEngine


def test_second_round_requires_new_acknowledgement_and_notice_is_not_gated():
    notices = []
    w, p, win, now, stop, calls = make_panel_watcher(PROMPT, on_detected=notices.append)
    VisualIntervention(w, SimpleNamespace(run=lambda _: False))
    w._window = win
    w._spawn = lambda name, job: job()
    try:
        w.tick()
        assert notices == [1] and calls == []
        assert w.acknowledge_pause(1)
        w.tick()
        count = len(calls)
        w._round.base.phase = 'SUCCEEDED'
        w.rearm(1)
        now[0] = 1.
        w.tick()
        w.tick()
        assert notices == [1, 2]
        assert len(calls) == count
        assert not w.acknowledge_pause(1)
        assert w.acknowledge_pause(2)
        w.tick()
        assert len(calls) > count
    finally:
        w.close()


def test_multiple_pauses_preserve_total_hold_budget():
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'key_press', 'key': 'a', 'hold_ms': 10000}])
    original, second = player._raw_sleep, [False]
    def sleep(seconds):
        original(seconds)
        if not second[0] and now[0] >= 9:
            second[0] = runtime.pending = True
    player._raw_sleep = sleep
    assert player.play(script).ok
    assert runtime.pauses == 2
    assert now[0] == pytest.approx(20.)
    assert backend.calls.count(('key_down', 'a')) == backend.calls.count(('key_up', 'a')) == 3


def test_wait_timeout_excludes_pause_and_discards_old_hit():
    actions = [{'type': 'wait_text', 'pattern': 'target', 'timeout_ms': 1000, 'on_timeout': 'continue'}]
    player, script, p, backend, runtime, now, stop = scenario(actions, trigger=.3)
    calls = []
    def recognize(image):
        calls.append(now[0])
        return []
    player._platform = replace(p, screen_capture=FakeScreenCapture(),
                               ocr_engine=SimpleNamespace(recognize=recognize))
    assert player.play(script).ok
    assert now[0] == pytest.approx(6.)
    assert runtime.pauses == 1
    assert calls[-1] == pytest.approx(6.)


def test_native_ocr_result_returned_with_pause_is_discarded():
    actions = [{'type': 'click_text', 'pattern': 'target'}]
    player, script, p, backend, runtime, now, stop = scenario(actions)
    calls = []
    def recognize(image):
        calls.append(1)
        if len(calls) == 1:
            runtime.pending = True
            return [TextBox('target', 1, 1, 10, 10, 1.)]
        return []
    player._platform = replace(p, screen_capture=FakeScreenCapture(),
                               ocr_engine=SimpleNamespace(recognize=recognize))
    assert player.play(script).ok
    assert len(calls) == 2
    assert not any(c[0] == 'mouse_click' for c in backend.calls)


@pytest.mark.parametrize('mode', ['normal', 'game', 'message', 'scan'])
def test_native_keyboard_modes_release_before_handoff(mode):
    from keyboard_executor.platforms.win32.input import Win32InputBackend
    from tests.platforms.test_win32_input import SpyPdi, SpyKeyboard, SpyMouse, SpyUser32
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'key_press', 'key': 'a', 'hold_ms': 100}], trigger=.03)
    p.window_manager.windows[:] = [replace(p.window_manager.windows[0], handle=0x1234)]
    pdi, kb, user = SpyPdi(), SpyKeyboard(), SpyUser32()
    pdi.ops = kb.ops = user.ops = backend.calls
    native = Win32InputBackend(game_input_mode=mode == 'game',
        window_message_mode=mode == 'message', scan_pulse_mode=mode == 'scan',
        pdi=pdi, user32=user, keyboard=kb, mouse=SpyMouse(), sleep=player._raw_sleep)
    player._platform = replace(p, input_backend=native)
    result = player.play(script)
    assert result.ok, result.error
    assert runtime.pauses == 1
    index = next(i for i, c in enumerate(backend.calls) if c[0] == 'pause')
    if mode == 'normal':
        assert backend.calls[index-1][0] == 'release'
    elif mode == 'message':
        assert backend.calls[index-1][1] == 0x0101  # WM_KEYUP
    else:
        assert backend.calls[index-1] == ('keyUp', 'a')
    assert now[0] == pytest.approx(5.1, abs=.015)
