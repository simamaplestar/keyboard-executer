import logging
from types import SimpleNamespace

import pytest

from keyboard_executor.core.visual_intervention import VisualIntervention
from tests.core.test_sequence_panel_helpers import make_panel_watcher, PROMPT
from tests.core.test_sequence_watcher import setup_watcher


@pytest.mark.parametrize('panel', [True, False])
def test_runtime_requires_current_round_release_before_ai(panel):
    calls = []
    rec = SimpleNamespace(recognize=lambda samples, **kw: calls.append(samples) or [])
    if panel:
        w, p, win, now, stop, _ = make_panel_watcher(PROMPT, recognizer=rec)
    else:
        w, p, win, now, stop = setup_watcher(recognizer=rec)
    VisualIntervention(w, SimpleNamespace(run=lambda _: False))
    w._window = win
    w._spawn = lambda name, job: job()
    try:
        for _ in range(3):
            w.tick()
        assert w.requested.is_set()
        assert calls == [], 'AI ran before the Player released held keys'
        rid = w.snapshot().round_id
        assert not w.acknowledge_pause(rid + 1)
        assert calls == []
        assert w.acknowledge_pause(rid)
        w.tick()
        assert calls
        stop.set()
        assert not w.acknowledge_pause(rid)
    finally:
        w.close()


@pytest.mark.parametrize('state', ['closed', 'cancelled', 'running'])
def test_start_info_only_once_after_actual_start(caplog, state):
    w, p, win, now, stop, _ = make_panel_watcher(boxes=[])
    caplog.set_level(logging.INFO)
    if state == 'closed':
        w.close()
    if state == 'cancelled':
        stop.set()
    try:
        w.start(win)
        w.start(win)
        messages = [r.message for r in caplog.records if '監看已啟動' in r.message]
        assert len(messages) == (1 if state == 'running' else 0)
        if messages:
            assert '每秒 OCR' in messages[0]
            assert str(w._config.panel_region) in messages[0]
            assert 'Discord=未設定' in messages[0]
    finally:
        w.close()
