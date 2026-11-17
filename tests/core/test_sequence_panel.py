import numpy as np
import pytest
from keyboard_executor.core.sequence_panel import PanelReading


def reading(sid, index=1, char='A', **changes):
    return PanelReading(**(dict(sample_id=sid, state='present', index=index, char=char,
        input_box=(100, 600, 600, 750), confirm_box=(650, 600, 900, 750)) | changes))


def frame(sid, stamp):
    from keyboard_executor.core.sequence_panel import PanelFrame
    return PanelFrame(sid, stamp, np.zeros((300, 400, 3), np.uint8), (0, 0, 500, 500), 0)


def make_round():
    from keyboard_executor.core.sequence_panel import PanelRound
    return PanelRound(1, frame(1, 0), (10, 20, 400, 300))


def apply(r, sid, stamp, index, char, **changes):
    f = frame(sid, stamp)
    r.observe_prompt(f, 'present', stamp)
    r.register(f)
    r.apply(f, reading(sid, index, char, **changes), stamp)


def ready():
    r = make_round()
    for sid, index, char, stamp in [(1, 1, 'A', 0), (2, 2, 'B', 0), (3, 3, 'C', 0),
                                    (4, 1, 'A', 1), (5, 2, 'B', 1), (6, 3, 'C', 1)]:
        apply(r, sid, stamp, index, char)
    return r


def test_points_inside_offset_panel():
    from keyboard_executor.core.sequence_panel import resolve_panel_points
    a, b = resolve_panel_points(reading(1), reading(2), (10, 20, 400, 300))
    assert a == (150, 222)
    assert b == (320, 222)


def test_tiny_and_drifting_boxes_rejected():
    from keyboard_executor.core.sequence_panel import resolve_panel_points
    tiny = reading(1, input_box=(1, 1, 2, 2))
    with pytest.raises(ValueError): resolve_panel_points(tiny, tiny, (0, 0, 100, 100))
    moved = reading(2, input_box=(300, 600, 800, 750))
    with pytest.raises(ValueError): resolve_panel_points(reading(1), moved, (0, 0, 400, 300))


def test_sorted_answer_stable_target_and_age():
    r = ready()
    assert r.base.answer == 'ABC'
    assert r.target(2).input_point == (150, 222)
    assert r.target(3) is not None
    assert r.target(3.01) is None
    assert r.target(.9) is None


def test_latest_unknown_blocks_old_ai_success():
    r = ready()
    r.observe_prompt(frame(7, 3), 'unknown', 3)
    assert r.target(3) is None
    r.apply(frame(3, 2), reading(3, 2, 'B'), 3)
    assert r.target(3) is None


def test_conflicting_vote_after_lock_is_ignored():
    r = ready()
    apply(r, 7, 2, 1, 'X')
    assert r.base.phase == 'READY'
    assert r.base.answer == 'ABC'


def test_conflicting_votes_never_fail_and_majority_wins():
    r = make_round()
    apply(r, 1, 0, 1, 'A')
    apply(r, 2, 1, 1, 'X')
    assert r.base.phase == 'COLLECTING'
    assert r.base.collected_indices == ()
    apply(r, 3, 2, 1, 'A')
    assert r.base.phase == 'COLLECTING'  # 2:1 多數鎖定，不再視為衝突失敗
    assert r.base.collected_indices == (1,)


def test_tie_votes_never_lock():
    r = make_round()
    apply(r, 1, 0, 1, 'A')
    apply(r, 2, 1, 1, 'B')
    assert r.base.collected_indices == ()
    assert r.base.phase == 'COLLECTING'
    apply(r, 3, 2, 1, 'B')
    assert r.base.collected_indices == (1,)  # 2:1 由 B 勝出


def test_gradual_drift_must_keep_original_submission_points_inside_controls():
    from keyboard_executor.core.sequence_panel import PanelRound
    from tests.core.test_sequence_panel_helpers import make_panel_watcher
    w, p, win, now, stop, calls = make_panel_watcher()
    r = PanelRound(1, frame(1, 0), (0, 0, 400, 300))
    try:
        for sid in (1, 2, 3, 4, 5, 6):
            apply(r, sid, sid-1, (sid-1)%3+1, 'ABC'[(sid-1)%3],
                  input_box=(100, 600, 450, 750), confirm_box=(500, 600, 750, 750))
        now[0] = 6
        w._round, w._window = r, win
        w._validated_target = r.target(6)
        assert w._validated_target.confirm_point[0] == 250
        assert w.begin_submit(1) == 'ABC'
        for offset in range(1, 7):
            now[0] = 6+offset
            shift = 25*offset
            apply(r, 6+offset, now[0], 1, 'A', input_box=(100+shift, 600, 450+shift, 750),
                  confirm_box=(500+shift, 600, 750+shift, 750))
            if offset == 1:
                assert r.base.phase == 'SUBMITTING'
        assert r.base.phase == 'FAILED', 'original click x=250 is outside the new confirmation bounds'
    finally: w.close()


def test_unknown_can_retry_identical_pixels():
    r = make_round()
    apply(r, 1, 0, None, None, state='unknown', input_box=None, confirm_box=None)
    apply(r, 2, 1, 1, 'A')
    assert r.base.collected_indices == ()
    apply(r, 3, 2, 1, 'A')
    assert r.base.collected_indices == (1,)
    assert r.base.answer is None


@pytest.mark.parametrize('state', ['absent', 'unknown'])
def test_prompt_loss_during_submit_fails(state):
    r = ready()
    assert r.base.begin_submit(2)
    r.observe_prompt(frame(7, 3), state, 3)
    assert r.base.phase == 'FAILED'


def test_only_post_click_two_absent_samples_complete():
    r = ready()
    r.base.begin_submit(2)
    r.base.mark_clicked(3)
    r.observe_prompt(frame(7, 2.5), 'absent', 3.5)
    assert r.base.phase == 'VERIFYING'
    r.observe_prompt(frame(8, 4), 'absent', 4)
    r.observe_prompt(frame(9, 5), 'unknown', 5)
    r.observe_prompt(frame(10, 6), 'absent', 6)
    assert r.base.phase == 'VERIFYING'
    r.observe_prompt(frame(11, 7), 'absent', 7)
    assert r.base.phase == 'SUCCEEDED'


def test_ai_absent_conflicts_with_ocr():
    r = make_round()
    apply(r, 1, 0, None, None, state='absent', input_box=None, confirm_box=None)
    assert r.base.phase == 'FAILED'


def test_distinct_time_required_for_layout():
    r = make_round()
    for sid in (1, 2, 3, 4, 5, 6):
        apply(r, sid, 0, (sid-1)%3+1, 'ABC'[(sid-1)%3])
    assert r.base.answer == 'ABC'
    assert r.target(0) is None


@pytest.mark.parametrize('time', [25, 30])
def test_deadline_never_renews(time):
    r = ready()
    r.base.check_time(time)
    assert r.base.phase == 'FAILED'
    assert r.target(time) is None


def test_unregistered_reading_ignored():
    r = make_round()
    r.apply(frame(5, 1), reading(5), 1)
    assert r.base.collected_indices == ()
