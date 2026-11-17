"""Deterministic reproductions of the independent review's input-safety races."""
from dataclasses import replace
import threading
import numpy as np
import pytest
from keyboard_executor.platforms.base import MouseButton, TextBox
from tests.core.test_sequence_watcher import setup_watcher
from tests.core.test_sequence_input import ready_round
from tests.core.test_sequence_submitter import build


def test_stale_trigger_ocr_after_resize_cannot_request_input():
    watcher, platform, win, now, stop = setup_watcher()
    watcher._window = win
    def ocr(image):
        platform.window_manager.windows[:] = [replace(win, width=700)]
        return [TextBox("請按照號碼順序輸入文字",0,0,100,20,.99)]
    platform.ocr_engine.recognize = ocr
    watcher._ocr(0, (1,0,np.zeros((30,30,3),np.uint8),(0,0,500,500)))
    assert not watcher.requested.is_set()


def test_second_absence_ocr_after_focus_loss_cannot_resume():
    watcher, platform, win, now, stop = setup_watcher()
    watcher._window = win
    r = watcher._round = ready_round()
    watcher._round_geometry = (0,0,500,500)
    r.begin_submit(117)
    r.mark_clicked(119)
    r.observe_absence(126,126,valid=True,absent=True)
    now[0] = 127
    def ocr(image):
        platform.window_manager.windows[:] = [replace(win,is_active=False)]
        return []
    platform.ocr_engine.recognize = ocr
    watcher._ocr(0, (2,127,np.zeros((30,30,3),np.uint8),(0,0,500,500)))
    assert watcher.snapshot().phase != "SUCCEEDED"


def test_submitter_cannot_adopt_new_geometry_after_validated_prompt():
    submitter, watcher, platform, win, stop, now = build()
    original = watcher.snapshot
    def snapshot():
        snap = original()
        snap.window_geometry = (0,0,500,500)
        return snap
    watcher.snapshot = snapshot
    platform.window_manager.refresh = lambda _: replace(win,width=700)
    assert not submitter.run(win)
    assert platform.input_backend.calls == []


def test_absence_during_submitting_revokes_remaining_input():
    watcher, platform, win, now, stop = setup_watcher()
    watcher._window = win
    watcher._round = ready_round()
    watcher._round_geometry = (0,0,500,500)
    now[0] = 117
    watcher._round.begin_submit(117)
    platform.ocr_engine.recognize = lambda _: []
    watcher._ocr(0, (2,117,np.zeros((30,30,3),np.uint8),(0,0,500,500)))
    assert watcher.snapshot().phase == "FAILED"


@pytest.mark.parametrize("game", [False,True])
def test_real_backend_settle_cancellation_prevents_click(game):
    from keyboard_executor.platforms.win32.input import Win32InputBackend
    from tests.platforms.test_win32_input import SpyPdi, SpyKeyboard, SpyMouse
    cancelled = threading.Event()
    pdi, mouse = SpyPdi(), SpyMouse()
    backend = Win32InputBackend(game_input_mode=game, pdi=pdi if game else None,
        keyboard=SpyKeyboard(), mouse=mouse, sleep=lambda _: cancelled.set())
    def check():
        if cancelled.is_set(): raise InterruptedError("deadline/stop")
    with pytest.raises(InterruptedError):
        backend.mouse_click_checked(330,220,MouseButton.LEFT,1,check=check)
    assert not any(op[0] == "click" for op in (pdi.ops + mouse.ops))


def test_submitter_deadline_during_real_confirm_settle_never_dispatches():
    from keyboard_executor.platforms.win32.input import Win32InputBackend
    from tests.platforms.test_win32_input import SpyPdi, SpyKeyboard, SpyMouse
    submitter, watcher, platform, win, stop, now = build()
    pdi = SpyPdi()
    settles = []
    def sleep(seconds):
        settles.append(seconds)
        if sum(op[0] == 'moveTo' for op in pdi.ops) == 2:
            now[0] = 30
    platform.input_backend = Win32InputBackend(game_input_mode=True, pdi=pdi,
        keyboard=SpyKeyboard(), mouse=SpyMouse(), sleep=sleep)
    assert not submitter.run(win)
    assert stop.is_set()
    assert watcher.clicked == 0
    assert len([op for op in pdi.ops if op[0] == "click"]) == 1


def test_chat_refresh_cannot_restore_focus_after_preemption():
    from tests.core.test_chat_reply import make_session
    session, _, win, _, _, _, _ = make_session()
    requested = threading.Event()
    session.set_input_preempted(requested.is_set)
    wm = session._platform.window_manager
    def refresh(_):
        requested.set()
        return win
    wm.refresh = refresh
    try:
        session._restore_window(win)
        assert wm.activated == []
    finally:
        session.close()


def test_focus_lost_during_completion_callback_cannot_resume_player():
    watcher, platform, win, now, stop = setup_watcher()
    watcher._window = win
    watcher._round_geometry = (0,0,500,500)
    r = watcher._round = ready_round()
    r.begin_submit(117)
    r.mark_clicked(119)
    r.observe_absence(126,126,valid=True,absent=True)
    r.observe_absence(127,127,valid=True,absent=True)
    now[0] = 128
    def progress(record):
        platform.window_manager.windows[:] = [replace(win,is_active=False)]
    watcher._progress = progress
    watcher.rearm(7)
    assert stop.is_set()


def test_punctuation_only_prompt_cannot_match_all_ocr_frames():
    from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
    from keyboard_executor.core.models import ScriptValidationError
    from tests.core.test_sequence_input_config import config_data
    config = config_data()
    config["prompt_text"] = "。 ！"
    with pytest.raises(ScriptValidationError): sequence_config_from_dict(config)
