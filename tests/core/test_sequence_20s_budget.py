"""18s prepare / 20s confirm / 30s verify: real clocks/state and input guards.

No native input, network or paid AI. Fakes stop at capture/OS/provider boundaries.
"""
from types import SimpleNamespace
import pytest

from keyboard_executor.core.sequence_input import SequenceRound
from keyboard_executor.core.sequence_panel import PanelRound
from tests.core.test_sequence_input import ready_round
from tests.core.test_sequence_panel import frame, reading
from tests.core.test_sequence_panel_helpers import make_panel_watcher, PROMPT
from tests.core.test_sequence_submitter import build


@pytest.mark.parametrize('ready', [False, True])
def test_preparation_deadline_is_18_seconds_from_original_capture(ready):
    r = ready_round() if ready else SequenceRound(7, 100)
    r.check_time(117.999)
    assert r.phase == ('READY' if ready else 'COLLECTING')
    r.check_time(118)
    assert r.phase == 'FAILED'
    assert r.deadline == 130


def test_last_answer_at_preparation_deadline_cannot_become_ready():
    r = SequenceRound(7, 100)
    for sid in (1, 2, 3):
        r.register(sid, str(sid), 100 + sid)
    r.apply(7, 1, 1, 'A', 110)
    r.apply(7, 2, 2, 'B', 117)
    r.apply(7, 3, 3, 'C', 118)
    assert r.phase == 'FAILED'
    assert r.answer is None


@pytest.mark.parametrize('method', ['check_time', 'mark_clicked'])
def test_submission_cannot_cross_20_seconds(method):
    r = ready_round()
    assert r.begin_submit(117.999)
    r.check_time(119.999)
    assert r.phase == 'SUBMITTING'
    getattr(r, method)(120)
    assert r.phase == 'FAILED'
    assert r.deadline == 130


def test_click_before_20_allows_verified_disappearance_after_20_but_not_after_30():
    for completed_at, expected in ((129.999, 'SUCCEEDED'), (130, 'FAILED')):
        r = ready_round()
        assert r.begin_submit(117.999)
        r.mark_clicked(119.999)
        r.check_time(120)
        assert r.phase == 'VERIFYING'
        r.observe_absence(121, 121, valid=True, absent=True)
        r.observe_absence(completed_at, completed_at, valid=True, absent=True)
        assert r.phase == expected
        assert r.deadline == 130


def scheduled_panel(start_at=0):
    w, p, win, now, stop, calls = make_panel_watcher(PROMPT)
    first = frame(1, 0)
    w._window, w._round = win, PanelRound(1, first, (0, 0, 400, 300))
    w._round.observe_prompt(first, 'present', 0)
    w._round.register(first)
    w._ai_pending.append(first)
    w._capture_busy = True  # controlled capture boundary; no background threads
    jobs = []
    w._spawn = lambda name, job: jobs.append((name, job))
    w.require_input_release()
    now[0] = start_at
    assert w.acknowledge_pause(1)
    w.tick()
    assert len(jobs) == 1 and jobs[0][0] == 'panel-ai'
    return w, now, stop, jobs


def test_pending_ai_is_not_killed_by_the_old_10_second_cap():
    w, now, stop, jobs = scheduled_panel()
    try:
        now[0] = 10
        w.tick()
        assert not stop.is_set()
        assert w.snapshot().phase == 'COLLECTING'
        now[0] = 17.999
        w.tick()
        assert not stop.is_set()
        now[0] = 18
        w.tick()
        assert stop.is_set()
        jobs[0][1]()  # late completion cannot resurrect the failed round
        assert w.snapshot().phase == 'FAILED'
        assert w.snapshot().answer is None
    finally:
        w.close()


def test_delayed_release_ack_does_not_restart_ai_budget():
    w, now, stop, jobs = scheduled_panel(12)
    observed = []
    def recognize(samples, *, should_abort):
        now[0] = 18
        observed.append(should_abort())
        return [reading(1)]
    w._recognizer = SimpleNamespace(recognize=recognize)
    try:
        jobs[0][1]()
        assert observed == [True]
        assert stop.is_set()  # provider abort must publish phase expiry without another supervisor tick
        w.tick()
        assert w.snapshot().phase == 'FAILED'
        assert w.snapshot().answer is None
        assert w.snapshot().deadline == 30
    finally:
        w.close()


def test_later_ai_batches_share_the_original_preparation_budget():
    w, now, stop, jobs = scheduled_panel()
    try:
        jobs[0][1]()
        second = frame(2, 12)
        now[0] = 12
        w._round.observe_prompt(second, 'present', 12)
        w._round.register(second)
        w._ai_pending.append(second)
        w.tick()
        assert len(jobs) == 2
        now[0] = 18
        w.tick()
        assert stop.is_set()
        jobs[1][1]()
        assert w.snapshot().phase == 'FAILED'
        assert w.snapshot().deadline == 30
    finally:
        w.close()


def test_overshot_watchdog_reports_preparation_deadline_not_a_new_ai_timeout():
    w, now, stop, jobs = scheduled_panel()
    notices = []
    w._progress = lambda event: notices.append(event['message'])
    try:
        now[0] = 21
        w.tick()
        assert stop.is_set()
        for name, job in list(jobs):
            if name == 'panel-progress':
                job()
        assert any('18 秒' in text for text in notices)
    finally:
        w.close()


def test_delayed_ai_window_refresh_reports_original_phase_deadline():
    w, now, stop, jobs = scheduled_panel()
    notices = []
    w._progress = lambda event: notices.append(event['message'])
    def refresh(window):
        now[0] = 21
        return window
    w._platform.window_manager.refresh = refresh
    try:
        now[0] = 17.9
        jobs[0][1]()
        assert stop.is_set()
        for name, job in list(jobs):
            if name == 'panel-progress':
                job()
        assert any('18 秒' in text for text in notices)
    finally:
        w.close()


def test_layout_safety_observations_survive_18_until_confirmation_then_are_cancelled():
    w, p, win, now, stop, _ = make_panel_watcher(PROMPT)
    w._window = win
    r = w._round = PanelRound(1, frame(1, 0), (0, 0, 400, 300))
    for sid, stamp, index, char in [(1, 0, 1, 'A'), (2, 1, 2, 'B'), (3, 2, 3, 'C'),
                                    (6, 3, 1, 'A'), (7, 4, 2, 'B'), (8, 5, 3, 'C'),
                                    (9, 16, 1, 'A')]:
        f = frame(sid, stamp)
        r.observe_prompt(f, 'present', stamp)
        r.register(f)
        r.apply(f, reading(sid, index, char), stamp)
    now[0] = 17
    assert w.begin_submit(1) == 'ABC'
    f = frame(10, 17)
    r.observe_prompt(f, 'present', 17)
    r.register(f)
    w._ai_pending.append(f)
    jobs = []
    w._capture_busy = True
    w._spawn = lambda name, job: jobs.append(job)
    def recognize(samples, *, should_abort):
        assert not should_abort()
        return [reading(10, 1, 'A')]
    w._recognizer = SimpleNamespace(recognize=recognize)
    try:
        w.tick()
        now[0] = 18.5
        w.tick()
        assert not stop.is_set()
        jobs[0]()
        assert r._last_ai == 10
        assert r.base.phase == 'SUBMITTING'
        now[0] = 19.9
        w.mark_clicked(1)
        now[0] = 20
        w.tick()
        assert not stop.is_set()
        assert r.base.phase == 'VERIFYING'
    finally:
        w.close()


def test_submitter_does_not_start_typing_at_18_seconds():
    submitter, watcher, platform, win, stop, now = build()
    now[0] = 18
    assert not submitter.run(win)
    assert platform.input_backend.calls == []
    assert watcher.clicked == 0


def test_confirm_is_blocked_when_typing_crosses_20_seconds():
    submitter, watcher, platform, win, stop, now = build()
    now[0] = 17.5
    original = platform.input_backend.type_text
    def type_text(text):
        original(text)
        now[0] = 20
    platform.input_backend.type_text = type_text
    assert not submitter.run(win)
    assert stop.is_set()
    assert watcher.clicked == 0
    assert len([c for c in platform.input_backend.calls if c[0] == 'type_text']) == 1


def test_final_native_window_query_cannot_authorize_input_after_20_seconds():
    submitter, watcher, platform, win, stop, now = build()
    watcher.phase = 'SUBMITTING'
    now[0] = 19.9
    def refresh(window):
        now[0] = 20
        return win
    platform.window_manager.refresh = refresh
    with pytest.raises(RuntimeError):
        submitter._check(win, 1, (0, 0, 500, 500))
    assert not platform.input_backend.calls


def test_crossing_20_after_mark_clicked_never_dispatches_confirmation():
    submitter, watcher, platform, win, stop, now = build()
    now[0] = 17.5
    mark = watcher.mark_clicked
    def mark_clicked(rid):
        mark(rid)
        now[0] = 20
    watcher.mark_clicked = mark_clicked
    assert not submitter.run(win)
    assert len([c for c in platform.input_backend.calls if c[0] == 'mouse_click']) == 1


@pytest.mark.parametrize('after_typing,expected', [(119.999, True), (120, False)])
def test_submitter_uses_real_snapshot_deadlines_relative_to_capture(after_typing, expected):
    from keyboard_executor.core.sequence_watcher import SequenceSnapshot
    submitter, watcher, platform, win, stop, now = build()
    watcher.snapshot = lambda: SequenceSnapshot(1, watcher.phase, 'HDP', 130, watcher.failure)
    now[0] = 117.5
    original = platform.input_backend.type_text
    def type_text(text):
        original(text)
        now[0] = after_typing
    platform.input_backend.type_text = type_text
    assert submitter.run(win) is expected
    assert watcher.clicked == int(expected)


def test_real_backend_settle_cannot_dispatch_confirmation_at_20_seconds():
    from keyboard_executor.platforms.win32.input import Win32InputBackend
    from tests.platforms.test_win32_input import SpyPdi, SpyKeyboard, SpyMouse
    submitter, watcher, platform, win, stop, now = build()
    now[0] = 17.5
    pdi = SpyPdi()
    def sleep(_):
        if sum(op[0] == 'moveTo' for op in pdi.ops) == 2:
            now[0] = 20
    platform.input_backend = Win32InputBackend(game_input_mode=True, pdi=pdi,
        keyboard=SpyKeyboard(), mouse=SpyMouse(), sleep=sleep)
    assert not submitter.run(win)
    assert watcher.clicked == 0
    assert len([op for op in pdi.ops if op[0] == 'click']) == 1
