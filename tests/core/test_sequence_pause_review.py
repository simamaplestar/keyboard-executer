from dataclasses import replace
from types import SimpleNamespace

import pytest

from keyboard_executor.core.visual_intervention import VisualIntervention
from keyboard_executor.platforms.base import TextBox
from tests.core.test_player_sequence_pause import scenario
from tests.core.test_sequence_panel_helpers import make_panel_watcher, PROMPT
from tests.core.test_sequence_watcher import setup_watcher
from tests.fakes import FakeScreenCapture


def test_resume_deadline_rechecked_after_blocking_window_query():
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'key_press', 'key': 'a', 'hold_ms': 10000}])
    runtime.resume_allowed = lambda: now[0] < 9.
    refresh = p.window_manager.refresh
    def slow_refresh(win):
        if runtime.pauses:
            now[0] = 10.
        return refresh(win)
    p.window_manager.refresh = slow_refresh
    result = player.play(script)
    assert not result.ok
    assert backend.calls == [('key_down', 'a'), ('key_up', 'a'), ('pause', 3.)]


def test_blocking_resume_log_cannot_hold_or_restore_keys_after_stop(monkeypatch):
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'key_press', 'key': 'a', 'hold_ms': 10000}])
    monkeypatch.setattr('keyboard_executor.core.sequence_pause.logger.info', lambda *args: stop.set())
    assert not player.play(script).ok
    assert backend.calls.count(('key_down', 'a')) == 1


@pytest.mark.parametrize('panel', [True, False])
def test_runtime_retains_round_deadline_after_rearm(panel):
    if panel:
        w, p, win, now, stop, _ = make_panel_watcher(PROMPT)
    else:
        w, p, win, now, stop = setup_watcher()
    def submit(win):
        r = w._round.base if panel else w._round
        r.phase = 'SUCCEEDED'
        return True
    runtime = VisualIntervention(w, SimpleNamespace(run=submit))
    w._window = runtime._window = win
    w._spawn = lambda name, job: job()
    try:
        w.tick()
        assert runtime.pause_for_sequence(None, win)
        assert w.snapshot().round_id is None
        assert runtime.resume_allowed()
        now[0] = 31.
        assert not runtime.resume_allowed()
    finally:
        w.close()


def test_short_combo_detected_between_keys_never_sends_remaining_key():
    player, script, p, backend, runtime, now, stop = scenario(
        [{'type': 'key_combo', 'keys': ['ctrl', 'a']}])
    original = backend.key_down
    def down(key):
        original(key)
        if key == 'ctrl':
            runtime.pending = True
    backend.key_down = down
    assert player.play(script).ok
    assert backend.calls == [('key_down', 'ctrl'), ('key_up', 'ctrl'), ('pause', 0.)]


def test_if_branch_is_rechecked_when_paused_before_first_effect():
    actions = [{'type': 'if_text', 'pattern': 'target',
                'then': [{'type': 'text_input', 'text': 'old'}],
                'else': [{'type': 'text_input', 'text': 'new'}]}]
    player, script, p, backend, runtime, now, stop = scenario(actions)
    reads = []
    def recognize(image):
        reads.append(1)
        return [TextBox('target', 0, 0, 10, 10, 1.)] if len(reads) == 1 else []
    player._platform = replace(p, screen_capture=FakeScreenCapture(),
                               ocr_engine=SimpleNamespace(recognize=recognize))
    triggered = [False]
    def on_step(info):
        if info['type'] == 'text_input' and not triggered[0]:
            triggered[0] = runtime.pending = True
    player._on_step = on_step
    result = player.play(script)
    assert result.ok, result.error
    assert len(reads) == 2
    assert ''.join(c[1] for c in backend.calls if c[0] == 'type_text') == 'new'


def test_if_committed_prefix_is_not_replayed_or_rebranched():
    actions = [{'type': 'if_text', 'pattern': 'target',
                'then': [{'type': 'text_input', 'text': 'A'}, {'type': 'text_input', 'text': 'B'}],
                'else': [{'type': 'text_input', 'text': 'wrong'}]}]
    player, script, p, backend, runtime, now, stop = scenario(actions)
    reads = []
    def recognize(image):
        reads.append(1)
        return [TextBox('target', 0, 0, 10, 10, 1.)] if len(reads) == 1 else []
    player._platform = replace(p, screen_capture=FakeScreenCapture(),
                               ocr_engine=SimpleNamespace(recognize=recognize))
    def on_step(info):
        if info['type'] == 'text_input' and info['index'] == 1:
            runtime.pending = True
    player._on_step = on_step
    assert player.play(script).ok
    assert len(reads) == 1
    assert ''.join(c[1] for c in backend.calls if c[0] == 'type_text') == 'AB'
