import pytest


def new_round():
    from keyboard_executor.core.sequence_input import SequenceRound
    return SequenceRound(7, 100.0)


def ready_round():
    r = new_round()
    for sid in (1, 2, 3):
        assert r.register(sid, str(sid), 100.0 + sid)
    for sid, index, char in [(1, 3, "p"), (2, 1, "h"), (3, 2, "d")]:
        r.apply(7, sid, index, char, 104.0)
    return r


def test_out_of_order_and_two_new_absences_required():
    r = ready_round()
    assert r.answer == "HDP"
    assert r.begin_submit(117)
    assert not r.begin_submit(117)
    r.mark_clicked(119)
    for captured in [118, 126, 126, 126.5]:
        r.observe_absence(captured, 126.5, valid=True, absent=True)
    assert r.phase == "VERIFYING"
    r.observe_absence(127, 127, valid=True, absent=True)
    assert r.phase == "SUCCEEDED"
    r.check_time(131)
    assert r.phase == "SUCCEEDED"


@pytest.mark.parametrize("now", [118, 120, 130, 131])
def test_cutoff_never_resurrects(now):
    r = ready_round()
    assert not r.begin_submit(now)
    r.apply(7, 1, 3, "P", 131)
    assert r.phase == "FAILED"


@pytest.mark.parametrize("index,char", [(True,"P"),(1.0,"P"),(0,"P"),(4,"P"),(1,"Ｐ"),(1,"ß"),(1,"PP"),(1,None)])
def test_invalid_values_do_not_form_answer(index, char):
    r = new_round()
    r.register(1, "x", 101)
    r.apply(7, 1, index, char, 102)
    assert r.answer is None
    assert r.phase == "COLLECTING"


def test_pending_conflict_not_ignored_when_three_indices_seen():
    r = new_round()
    for sid in range(1, 5): r.register(sid, str(sid), 101)
    for sid in range(1, 4): r.apply(7, sid, sid, "A", 102)
    assert r.phase == "COLLECTING"
    assert not r.register(5, "5", 103)
    r.apply(7, 4, 1, "B", 103)
    assert r.phase == "FAILED"


def test_duplicates_limits_and_generation():
    r = new_round()
    assert r.register(1, "same", 101)
    assert not r.register(2, "same", 102)
    r.apply(6, 1, 1, "A", 102)
    r.apply(7, 1, 1, "A", 102)
    r.apply(7, 1, 1, "B", 102)
    assert r.phase == "COLLECTING"
    for sid in range(2, 31): assert r.register(sid, str(sid), 102)
    assert not r.register(31, "31", 102)


def test_invalid_absence_resets_streak_and_deadline_never_restarts():
    r = ready_round()
    r.begin_submit(117)
    r.mark_clicked(119)
    r.observe_absence(126, 126, valid=True, absent=True)
    r.observe_absence(127, 127, valid=False, absent=True)
    r.observe_absence(128, 128, valid=True, absent=True)
    assert r.phase == "VERIFYING"
    r.observe_absence(129, 130, valid=True, absent=True)
    assert r.phase == "FAILED"
    assert r.deadline == 130


def test_same_character_in_multiple_indices_and_unknown_pending():
    r = new_round()
    for sid in range(4): r.register(sid, str(sid), 101)
    for sid in range(3): r.apply(7, sid, sid+1, "a", 102)
    r.apply(7, 3, None, None, 102)
    assert r.answer == "AAA"
    assert r.phase == "READY"
