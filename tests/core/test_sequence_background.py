"""背景（非前景）視窗的偵測與提交行為。

偵測不要求前景：視窗在背景但未被遮擋時 mss 仍取得到遊戲畫面，
測謊提示出現時必須能觸發回合並發出通知；輸入前由 submitter
負責把視窗切回前景，切不回來就安全失敗、不送任何輸入。
"""
from dataclasses import replace

from tests.core.test_sequence_watcher import setup_watcher, eventually
from tests.core.test_sequence_panel_helpers import make_panel_watcher, settle, step, PROMPT, ABSENT
from tests.core.test_sequence_submitter import build


def refresh_by_handle(platform):
    """真實 refresh 以 handle 識別視窗；is_active 變化不代表視窗消失。"""
    wm = platform.window_manager
    wm.refresh = lambda w: next((x for x in wm.windows if x.handle == w.handle), None)


def test_background_window_still_detects_prompt():
    watcher, platform, win, now, stop = setup_watcher()
    platform.window_manager.windows[:] = [replace(win, is_active=False)]
    refresh_by_handle(platform)
    try:
        watcher.start(win)
        assert watcher.requested.wait(2), "背景視窗應仍能偵測到提示"
        assert watcher.snapshot().phase == "COLLECTING"
    finally:
        stop.set()
        watcher.close()


def test_minimized_sized_window_skips_frame_without_error():
    from keyboard_executor.core.sequence_watcher import capture_region
    watcher, platform, win, _, _ = setup_watcher()
    platform.window_manager.windows[:] = [replace(win, width=0, height=0)]
    refresh_by_handle(platform)
    assert capture_region(platform, win, (0, 0, 20, 20)) is None
    platform.window_manager.windows[:] = [replace(win, x=-32000, y=-32000)]
    assert capture_region(platform, win, (0, 0, 20, 20)) is None
    watcher.close()


def test_panel_background_window_still_triggers_round():
    notices = []
    watcher, platform, win, now, stop, calls = make_panel_watcher(PROMPT, on_detected=notices.append)
    platform.window_manager.windows[:] = [replace(win, is_active=False)]
    refresh_by_handle(platform)
    try:
        watcher.start(win)
        step(watcher, platform, now, 1)
        assert watcher.snapshot().phase == "COLLECTING"
        eventually(lambda: notices == [1])
    finally:
        stop.set()
        watcher.close()


def test_panel_background_observation_cannot_confirm_disappearance():
    watcher, platform, win, now, stop, calls = make_panel_watcher(ABSENT)
    platform.ocr_engine._boxes = PROMPT
    try:
        watcher.start(win)
        for t in (1, 2, 3, 4, 5, 6):
            step(watcher, platform, now, t)
        # 數字辨識在背景執行緒；電腦忙時（完整測試）要等它完成才會進 READY
        settle(watcher, lambda: watcher.snapshot().phase == "READY")
        with watcher._lock:
            watcher._round.base.begin_submit(now[0])
            watcher._round.base.mark_clicked(now[0])
        platform.ocr_engine._boxes = ABSENT
        platform.window_manager.windows[:] = [replace(win, is_active=False)]
        refresh_by_handle(platform)
        step(watcher, platform, now, 8)
        step(watcher, platform, now, 9)
        assert watcher.snapshot().phase != "SUCCEEDED", "非前景畫面不能當作提示已消失"
    finally:
        stop.set()
        watcher.close()


def test_submitter_reactivates_background_window_before_input():
    submitter, watcher, platform, win, stop, now = build()
    platform.window_manager.windows[:] = [replace(win, is_active=False)]
    refresh_by_handle(platform)
    original = platform.window_manager.activate
    def activate(window):
        platform.window_manager.windows[:] = [replace(win, is_active=True)]
        return original(window)
    platform.window_manager.activate = activate
    assert submitter.run(win)
    assert platform.window_manager.activated, "輸入前應先把視窗切回前景"
    assert "".join(c[1] for c in platform.input_backend.calls if c[0] == "type_text") == "HDP"


def test_submitter_without_recoverable_focus_never_inputs():
    submitter, watcher, platform, win, stop, now = build()
    platform.window_manager.windows[:] = [replace(win, is_active=False)]
    refresh_by_handle(platform)
    assert not submitter.run(win)
    assert platform.input_backend.calls == []
    assert watcher.clicked == 0
