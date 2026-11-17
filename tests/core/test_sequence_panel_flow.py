from dataclasses import replace
import threading
import pytest
from keyboard_executor.core.sequence_submitter import SequenceSubmitter
from tests.fakes import FakeInputBackend
from tests.core.test_sequence_panel_helpers import make_panel_watcher, step, settle, PROMPT, ABSENT
from tests.core.test_sequence_panel import reading
from tests.core.test_sequence_watcher import eventually


def run_flow(fault=None, outcomes=None):
    notices = []
    outcomes = [] if outcomes is None else outcomes
    w, p, win, now, stop, calls = make_panel_watcher(
        ABSENT, on_detected=notices.append, on_outcome=lambda *a: outcomes.append(a))
    backend = p.input_backend = FakeInputBackend()
    submitter = SequenceSubmitter(p, w._config, w, stop, clock=lambda: now[0], target_provider=w.submission_target)
    worker = None
    result = []
    try:
        w.start(win)
        settle(w, lambda: bool(p.ocr_engine.calls) and not w._ocr_busy)
        assert calls == [] and notices == []
        p.ocr_engine._boxes = PROMPT
        for t in (1, 2, 3, 4, 5, 6):
            step(w, p, now, t)
            settle(w, lambda: len(calls) >= t and not w._ai_running)
        assert w.snapshot().phase == 'READY'
        eventually(lambda: notices == [1])
        if fault == 'cancel': stop.set()
        if fault == 'focus': p.window_manager.windows[:] = [replace(win, is_active=False)]
        if fault == 'geometry': p.window_manager.windows[:] = [replace(win, width=450)]
        if fault == 'timeout': now[0] = 26
        if fault == 'unknown': p.ocr_engine._boxes = []
        entered = threading.Event()
        original = w.validate_prompt
        def validate(rid): entered.set(); return original(rid)
        w.validate_prompt = validate
        worker = threading.Thread(target=lambda: result.append(submitter.run(win)))
        worker.start()
        if fault in {'cancel', 'timeout'}:
            settle(w, lambda: bool(result))
        else:
            assert entered.wait(2)
            now[0] = 7
            if fault in {'focus', 'geometry'}:
                settle(w, lambda: bool(result))
            elif fault == 'unknown':
                settle(w, lambda: len(p.ocr_engine.calls) >= 8 and not w._ocr_busy)
                assert not any(c[0] == 'mouse_click' for c in backend.calls)
                now[0] = 26
                settle(w, lambda: bool(result))
            else:
                settle(w, lambda: w.snapshot().phase == 'VERIFYING')
                ai_before_absence = len(calls)
                p.ocr_engine._boxes = ABSENT
                step(w, p, now, 8)
                assert w.snapshot().phase == 'VERIFYING'
                step(w, p, now, 9)
                settle(w, lambda: bool(result))
                assert len(calls) == ai_before_absence
        worker.join(2)
        if fault != 'cancel':
            eventually(lambda: bool(outcomes))
        return result[0], backend.calls, notices
    finally:
        stop.set(); w.close()
        if worker: worker.join(2)


def test_full_flow_ocr_ai_input_and_local_disappearance():
    outcomes = []
    completed, calls, notices = run_flow(outcomes=outcomes)
    assert completed
    # 實機 2026-10-30：只有「開始辨識」通知，成功與否都沒有後續通知。
    assert len(outcomes) == 1 and outcomes[0][:2] == (1, True) and 'ABC' in outcomes[0][2]
    assert ''.join(c[1] for c in calls if c[0] == 'type_text') == 'ABC'
    assert len([c for c in calls if c[0] == 'mouse_click']) == 2
    assert notices == [1]


@pytest.mark.parametrize('fault', ['cancel', 'focus', 'geometry', 'timeout', 'unknown'])
def test_unsafe_flow_never_confirms(fault):
    outcomes = []
    completed, calls, notices = run_flow(fault, outcomes)
    assert not completed
    if fault != 'cancel':
        assert len(outcomes) == 1 and outcomes[0][:2] == (1, False) and outcomes[0][2]
    assert not any(c[0] == 'mouse_click' for c in calls)
    assert notices == [1]
