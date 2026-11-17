from dataclasses import replace
from types import SimpleNamespace
import threading
import pytest
from tests.core.test_sequence_panel_helpers import make_panel_watcher, step, settle, PROMPT, ABSENT
from tests.core.test_sequence_watcher import eventually


@pytest.mark.parametrize('boxes', [[], ABSENT])
def test_idle_never_calls_ai(boxes):
    w, p, win, now, stop, calls = make_panel_watcher(boxes)
    try:
        w.start(win)
        settle(w, lambda: len(p.ocr_engine.calls) == 1 and not w._ocr_busy)
        for t in (1, 2, 3): step(w, p, now, t)
        assert calls == []
        assert not w.requested.is_set()
        assert not stop.is_set()
    finally: w.close()


def test_trigger_frame_sent_and_notice_once_before_ai_returns():
    entered, release = threading.Event(), threading.Event()
    samples, notices = [], []
    def recognize(batch, **kwargs):
        samples.extend(batch); entered.set(); release.wait(3); return []
    w, p, win, now, stop, _ = make_panel_watcher(PROMPT, SimpleNamespace(recognize=recognize), notices.append)
    try:
        w.start(win)
        assert entered.wait(2)
        eventually(lambda: len(notices) == 1)
        assert samples[0].sample_id == 1
        assert samples[0].image[0, 0, 0] == 0
        for t in (1, 2, 3): step(w, p, now, t)
        assert notices == [1]
        # 第一個請求卡住時，後面的畫面改用其他平行請求送出（最多 3 個同時）。
        eventually(lambda: len(samples) == 3)
        assert len(p.screen_capture.captures) >= 4
        now[0] = 10
        w.tick()
        assert not stop.is_set()
        now[0] = 18
        w.tick()
        assert stop.is_set()
    finally: w.close(); release.set()


def test_slow_ocr_counts_capture_time_and_skips_expired_ai():
    entered, release = threading.Event(), threading.Event()
    def recognize(image):
        entered.set(); release.wait(3); return PROMPT
    w, p, win, now, stop, calls = make_panel_watcher()
    p.ocr_engine = SimpleNamespace(recognize=recognize)
    try:
        w.start(win)
        assert entered.wait(2)
        now[0] = 26
        release.set()
        assert stop.wait(2)
        assert w.snapshot().deadline == 30
        assert calls == []
    finally: w.close(); release.set()


def test_ocr_result_for_moved_window_cannot_trigger():
    entered, release = threading.Event(), threading.Event()
    def recognize(image):
        entered.set(); release.wait(3); return PROMPT
    w, p, win, now, stop, calls = make_panel_watcher()
    p.ocr_engine = SimpleNamespace(recognize=recognize)
    try:
        w.start(win); assert entered.wait(2)
        p.window_manager.windows[:] = [replace(win, x=50)]
        release.set()
        eventually(lambda: not w._ocr_busy)
        assert calls == []
        assert not w.requested.is_set()
    finally: w.close(); release.set()


def test_ready_requires_three_indices_and_fresh_layout():
    w, p, win, now, stop, calls = make_panel_watcher(PROMPT)
    try:
        w.start(win)
        settle(w, lambda: len(calls) == 1 and not w._ai_running)
        for t in (1, 2, 3, 4, 5):
            step(w, p, now, t)
            settle(w, lambda: len(calls) >= t+1 and not w._ai_running)
        assert w.snapshot().phase == 'READY'
        assert w.snapshot().answer == 'ABC'
        assert w.submission_target(1).round_id == 1
        now[0] = 8  # 最後定位於 t=5，超過 2 秒新鮮度就退回 COLLECTING
        assert w.snapshot().phase == 'COLLECTING'
    finally: w.close()


def test_blocked_notice_does_not_block_deadline_or_ai():
    entered, release = threading.Event(), threading.Event()
    def notice(rid): entered.set(); release.wait(3)
    w, p, win, now, stop, calls = make_panel_watcher(PROMPT, on_detected=notice)
    try:
        w.start(win); assert entered.wait(2)
        settle(w, lambda: bool(calls))
        now[0] = 25
        assert stop.wait(1)
    finally: release.set(); w.close()


def test_os_query_on_ai_thread_cannot_hold_watchdog_lock():
    entered, release = threading.Event(), threading.Event()
    w, p, win, now, stop, calls = make_panel_watcher(PROMPT)
    original = p.window_manager.refresh
    def refresh(window):
        if threading.current_thread().name == 'panel-ai':
            entered.set(); release.wait(3)
        return original(window)
    p.window_manager.refresh = refresh
    try:
        w.start(win); assert entered.wait(2)
        now[0] = 30
        assert stop.wait(.3), 'OS query blocked the independent deadline supervisor'
    finally: release.set(); w.close()


def test_provider_abort_at_request_deadline_still_stops():
    from keyboard_executor.core.ai.provider import AiAborted
    from keyboard_executor.core.sequence_panel import PanelRound
    from tests.core.test_sequence_panel import frame
    w, p, win, now, stop, calls = make_panel_watcher(PROMPT)
    def recognize(samples, **kwargs):
        now[0] = 10
        raise AiAborted()
    w._recognizer = SimpleNamespace(recognize=recognize)
    first = frame(1, 0)
    w._window, w._round = win, PanelRound(1, first, (0, 0, 400, 300))
    token = (0, 1, threading.Event(), 10)
    w._ai_tokens[token] = (0, [1])
    try:
        w._recognize(token, [first])
        assert stop.is_set()
    finally: w.close()


def test_queue_overflow_stops_instead_of_dropping_oldest():
    from keyboard_executor.core.sequence_panel import PanelRound
    from tests.core.test_sequence_panel import frame
    w, p, win, now, stop, calls = make_panel_watcher(PROMPT)
    first = frame(1, 0)
    w._window, w._round = win, PanelRound(1, first, (0, 0, 400, 300))
    try:
        for sid in range(31): w._enqueue(w._ocr_pending, frame(sid+1, 0))
        w.tick()
        assert stop.is_set()
        assert calls == []
        assert w._ocr_pending[0].sample_id == 1
    finally: w.close()


def test_close_invalidates_late_failure():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def recognize(batch, **kwargs):
        entered.set(); release.wait(3); finished.set(); raise RuntimeError('late')
    w, p, win, now, stop, _ = make_panel_watcher(PROMPT, SimpleNamespace(recognize=recognize))
    other, op, owin, onow, ostop, ocalls = make_panel_watcher(PROMPT)
    try:
        w.start(win); assert entered.wait(2)
        w.close(); other.start(owin)
        release.set(); assert finished.wait(2)
        settle(other, lambda: bool(ocalls))
        assert not stop.is_set()
        assert not ostop.is_set()
    finally: release.set(); w.close(); other.close()


def test_one_stalled_ai_request_does_not_sink_the_round():
    # 實機 2026-10-30 10:38：一次 AI 請求卡住超過 18 秒，整回合失敗、腳本停止。
    from tests.core.test_sequence_panel import reading
    release, calls = threading.Event(), []
    def recognize(samples, should_abort, **kwargs):
        calls.extend(samples)
        if samples[0].sample_id == 1:
            while not should_abort() and not release.is_set():
                release.wait(.01)
            raise AiAborted()
        return [reading(s.sample_id, 1, 'ABC'[(s.sample_id-2) % 3]) for s in samples]
    from keyboard_executor.core.ai.provider import AiAborted
    w, p, win, now, stop, _ = make_panel_watcher(PROMPT, SimpleNamespace(recognize=recognize))
    try:
        w.start(win)
        eventually(lambda: len(calls) >= 1)
        for t in range(1, 9):
            step(w, p, now, t)
            settle(w, lambda: len(w._ai_tokens) <= 1)
        assert w.snapshot().phase == 'READY'
        assert w.snapshot().answer == 'ABC'
        assert not stop.is_set()
    finally:
        release.set(); w.close()
