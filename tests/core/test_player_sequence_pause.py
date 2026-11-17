from dataclasses import replace
import threading

import pytest

from keyboard_executor.core.player import Player
from tests.core.test_player_flow import make_platform, make_script


def scenario(actions, trigger=3., duration=5., cancelled=False):
    platform, backend = make_platform()
    platform.window_manager.windows[:] = [replace(platform.window_manager.windows[0], is_active=True)]
    now, triggered = [0.], [False]
    stop = threading.Event()

    class Runtime:
        supports_sequence_input = True
        pending = False
        pauses = 0
        def __call__(self, script, win):
            pass
        def sequence_pending(self):
            return self.pending
        def pause_for_sequence(self, script, win):
            self.pauses += 1
            backend.calls.append(('pause', round(now[0], 6)))
            now[0] += duration
            self.pending = False
            if cancelled:
                stop.set()
            return not cancelled

    runtime = Runtime()
    def sleep(seconds):
        end = now[0] + seconds
        if not triggered[0] and end >= trigger:
            now[0] = trigger
            triggered[0] = runtime.pending = True
        else:
            now[0] = end
    script = make_script(actions, settings={'sequence_input': {
        'enabled': True, 'mode': 'panel', 'panel_region': [0, 0, 90, 90]}})
    player = Player(platform, stop_event=stop, sleep=sleep, clock=lambda: now[0], on_action_boundary=runtime)
    return player, script, platform, backend, runtime, now, stop


@pytest.mark.parametrize('action', [
    {'type': 'key_press', 'key': 'a', 'hold_ms': 10000},
    {'type': 'key_combo', 'keys': ['ctrl', 'a'], 'hold_ms': 10000},
    {'type': 'delay', 'ms': 10000},
])
def test_immediate_pause_resumes_only_remaining_duration(action):
    player, script, platform, backend, runtime, now, stop = scenario([action])
    result = player.play(script)
    assert result.ok, result.error
    assert runtime.pauses == 1
    assert now[0] == pytest.approx(15.)
    if action['type'] == 'key_press':
        assert backend.calls == [('key_down', 'a'), ('key_up', 'a'), ('pause', 3.),
                                 ('key_down', 'a'), ('key_up', 'a')]
    elif action['type'] == 'key_combo':
        assert backend.calls == [('key_down', 'ctrl'), ('key_down', 'a'),
                                 ('key_up', 'a'), ('key_up', 'ctrl'), ('pause', 3.),
                                 ('key_down', 'ctrl'), ('key_down', 'a'),
                                 ('key_up', 'a'), ('key_up', 'ctrl')]


def test_stop_during_pause_never_represses_key():
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'key_press', 'key': 'a', 'hold_ms': 10000}], cancelled=True)
    result = player.play(script)
    assert not result.ok
    assert stop.is_set()
    assert backend.calls == [('key_down', 'a'), ('key_up', 'a'), ('pause', 3.)]


def test_short_tap_is_not_replayed_after_pause():
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'key_press', 'key': 'a'}], trigger=.03)
    assert player.play(script).ok
    assert runtime.pauses == 1
    assert backend.calls == [('key_down', 'a'), ('key_up', 'a'), ('pause', .03)]


def test_partial_text_continues_without_replaying_prefix():
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'text_input', 'text': 'ABC'}])
    original = backend.type_text
    def type_text(text):
        original(text)
        if text == 'A':
            runtime.pending = True
    backend.type_text = type_text
    assert player.play(script).ok
    assert backend.calls == [('type_text', 'A'), ('pause', 0.), ('type_text', 'B'), ('type_text', 'C')]


def test_foreground_change_during_pause_prevents_restore():
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'key_press', 'key': 'a', 'hold_ms': 10000}])
    original = runtime.pause_for_sequence
    def pause(script, win):
        result = original(script, win)
        p.window_manager.windows.clear()
        return result
    runtime.pause_for_sequence = pause
    assert not player.play(script).ok
    assert sum(c == ('key_down', 'a') for c in backend.calls) == 1


def test_multiple_clicks_resume_only_unsent_clicks():
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'mouse_click', 'x': 10, 'y': 20, 'button': 'left', 'count': 3}])
    original = backend.mouse_click
    def click(x, y, button, count):
        original(x, y, button, count)
        if len(backend.calls) == 1:
            runtime.pending = True
    backend.mouse_click = click
    assert player.play(script).ok
    clicks = [c for c in backend.calls if c[0] == 'mouse_click']
    assert [c[-1] for c in clicks] == [1, 1, 1]
    assert backend.calls[1] == ('pause', 0.)


def test_drag_started_before_pause_stops_after_handling():
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'mouse_drag', 'from': [0, 0], 'to': [20, 20], 'button': 'left'},
         {'type': 'text_input', 'text': 'must not type'}])
    def drag(*args, check, before_press=None):
        check()
        before_press()
        backend.calls.append(('mouse_down',))
        runtime.pending = True
        try:
            check()
        finally:
            backend.calls.append(('mouse_up',))
    backend.mouse_drag_checked = drag
    result = player.play(script)
    assert not result.ok
    assert '拖曳' in result.error
    assert backend.calls == [('mouse_down',), ('mouse_up',), ('pause', 0.)]
    assert stop.is_set()


def test_release_failure_blocks_ai_handoff():
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'key_press', 'key': 'a', 'hold_ms': 10000}])
    def fail(key):
        raise RuntimeError('cannot release')
    backend.key_up = fail
    assert not player.play(script).ok
    assert runtime.pauses == 0


def test_direction_combo_in_pause_mode_keeps_arrow_outside_other_key():
    player, script, platform, backend, runtime, now, stop = scenario(
        [{'type': 'key_combo', 'keys': ['space', 'down']}], trigger=99.)
    assert player.play(script).ok
    assert backend.calls == [('key_down', 'down'), ('key_down', 'space'),
                             ('key_up', 'space'), ('key_up', 'down')]
    assert now[0] == pytest.approx(.3)


def test_direction_combo_pause_restores_arrow_first_and_finishes_hold():
    player, script, platform, backend, runtime, now, stop = scenario(
        [{'type': 'key_combo', 'keys': ['right', 'z'], 'hold_ms': 10000}])
    assert player.play(script).ok
    assert runtime.pauses == 1
    assert backend.calls == [('key_down', 'right'), ('key_down', 'z'),
                             ('key_up', 'z'), ('key_up', 'right'), ('pause', 3.),
                             ('key_down', 'right'), ('key_down', 'z'),
                             ('key_up', 'z'), ('key_up', 'right')]


def test_background_window_checkpoint_hands_off_instead_of_aborting():
    # 背景偵測到的回合：checkpoint 不得因失焦中止，submitter 會在輸入前切回前景。
    player, script, platform, backend, runtime, now, stop = scenario(
        [{'type': 'delay', 'ms': 10000}])
    platform.window_manager.windows[:] = [replace(platform.window_manager.windows[0],
                                                  is_active=False)]
    result = player.play(script)
    assert result.ok, result.error
    assert runtime.pauses == 1
    assert now[0] == pytest.approx(15.)


def test_closed_window_checkpoint_still_aborts():
    player, script, platform, backend, runtime, now, stop = scenario(
        [{'type': 'delay', 'ms': 10000}])
    original = platform.window_manager.refresh
    platform.window_manager.refresh = lambda w: None if runtime.pending else original(w)
    result = player.play(script)
    assert not result.ok
    assert runtime.pauses == 0
