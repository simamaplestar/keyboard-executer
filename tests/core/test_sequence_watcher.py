from dataclasses import replace
import threading
import time
from types import SimpleNamespace
import numpy as np
import pytest
from tests.fakes import FakeScreenCapture, FakeWindowManager, FakeOcrEngine
from keyboard_executor.platforms.base import WindowInfo, TextBox
from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
from tests.core.test_sequence_input_config import config_data


def eventually(check, timeout=2):
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "background work did not finish"
        threading.Event().wait(.005)


def setup_watcher(ocr=None, recognizer=None, progress=None):
    from keyboard_executor.core.sequence_watcher import SequenceWatcher
    now = [0.0]
    win = WindowInfo(1, "記事本", "app", 0, 0, 500, 500, True)
    cap = FakeScreenCapture(np.zeros((30, 30, 3), np.uint8))
    ocr = ocr or FakeOcrEngine([TextBox("請按照號碼順序輸入文字", 0, 0, 100, 20, .99)])
    platform = SimpleNamespace(screen_capture=cap, window_manager=FakeWindowManager([win]), ocr_engine=ocr)
    if recognizer is None:
        from keyboard_executor.core.ai.sequence_recognizer import SequenceReading
        recognizer = SimpleNamespace(recognize=lambda samples, **kw: [SequenceReading(s.sample_id, None, None) for s in samples])
    stop = threading.Event()
    watcher = SequenceWatcher(platform, sequence_config_from_dict(config_data()), recognizer, stop, progress, clock=lambda: now[0])
    return watcher, platform, win, now, stop


def test_slow_progress_callback_cannot_block_deadline_watchdog():
    entered, release = threading.Event(), threading.Event()
    def progress(record):
        entered.set()
        release.wait(3)
    watcher, _, win, now, stop = setup_watcher(progress=progress)
    try:
        watcher.start(win)
        assert entered.wait(2)
        now[0] = 30
        assert stop.wait(.3), "logging callback blocked the deadline watcher"
    finally:
        release.set()
        watcher.close()


def test_normalize_and_window_moved_frame_invalid():
    from keyboard_executor.core.sequence_watcher import capture_region, normalize_prompt
    assert normalize_prompt("請按照號碼順序輸入文字。\n") == "请按照号码顺序输入文字"
    watcher, platform, win, _, _ = setup_watcher()
    original = platform.screen_capture.capture
    def capture(rect):
        platform.window_manager.windows[:] = [replace(win, x=10)]
        return original(rect)
    platform.screen_capture.capture = capture
    assert capture_region(platform, win, (0, 0, 20, 20)) is None
    watcher.close()


def test_slow_ai_does_not_stop_sampling_and_cannot_outlive_deadline():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def recognize(samples, **kw):
        entered.set()
        release.wait(3)
        finished.set()
        return []
    watcher, platform, win, now, stop = setup_watcher(recognizer=SimpleNamespace(recognize=recognize))
    try:
        watcher.start(win)
        assert watcher.requested.wait(2)
        assert entered.wait(2)
        for t in (1, 2, 3):
            platform.screen_capture.image = np.full((30, 30, 3), t, np.uint8)
            before = len(platform.screen_capture.captures)
            now[0] = t
            watcher.tick()
            eventually(lambda: len(platform.screen_capture.captures) >= before + 2)
        now[0] = 30
        watcher.tick()
        assert stop.is_set()
        assert watcher.snapshot().phase == "FAILED"
        watcher.close()
        release.set()
        assert finished.wait(2)
        assert watcher.snapshot().phase in {"FAILED", "STOPPED"}
    finally:
        release.set()
        watcher.close()


def test_slow_prompt_ocr_counts_from_original_frame():
    entered, release = threading.Event(), threading.Event()
    def recognize(image):
        entered.set()
        release.wait(3)
        return [TextBox("請按照號碼順序輸入文字", 0, 0, 100, 20, .99)]
    watcher, _, win, now, stop = setup_watcher(ocr=SimpleNamespace(recognize=recognize))
    try:
        watcher.start(win)
        assert entered.wait(2)
        now[0] = 26
        release.set()
        assert stop.wait(2)
        assert watcher.snapshot().deadline == 30
    finally:
        release.set()
        watcher.close()


def test_closed_ocr_error_cannot_stop_next_runtime_with_same_handle():
    entered, release = threading.Event(), threading.Event()
    def recognize(image):
        entered.set()
        release.wait(3)
        raise RuntimeError("late failure")
    watcher, _, win, _, stop = setup_watcher(ocr=SimpleNamespace(recognize=recognize))
    other, _, same_win, _, other_stop = setup_watcher()
    try:
        watcher.start(win)
        assert entered.wait(2)
        watcher.close()
        other.start(same_win)
        assert other.requested.wait(2)
        release.set()
        eventually(lambda: not watcher._ocr_busy)
        assert not stop.is_set()
        assert not other_stop.is_set()
        assert other.snapshot().phase == "COLLECTING"
    finally:
        release.set()
        watcher.close()
        other.close()


def test_identical_frames_do_not_repeat_ai_and_close_invalidates_result():
    calls = []
    entered, release = threading.Event(), threading.Event()
    def recognize(samples, **kw):
        calls.append(samples)
        entered.set()
        release.wait(3)
        return []
    watcher, _, win, now, stop = setup_watcher(recognizer=SimpleNamespace(recognize=recognize))
    try:
        watcher.start(win)
        assert entered.wait(2)
        for t in (1,2,3):
            now[0] = t
            watcher.tick()
        watcher.close()
        release.set()
        assert len(calls) == 1
        assert watcher.snapshot().phase == "STOPPED"
    finally:
        release.set()
        watcher.close()
