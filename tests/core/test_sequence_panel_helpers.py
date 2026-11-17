import threading
from types import SimpleNamespace
import numpy as np
from keyboard_executor.platforms.base import WindowInfo, TextBox
from keyboard_executor.core.sequence_input_config import sequence_config_from_dict
from keyboard_executor.core.sequence_panel_vision import PanelVision
from tests.fakes import FakeScreenCapture, FakeWindowManager, FakeOcrEngine
from tests.core.test_sequence_panel import reading
from tests.core.test_sequence_watcher import eventually

PROMPT = [TextBox('請按照號碼順序輸入文字', 0, 0, 300, 30, .99)]
ABSENT = [TextBox('遊戲畫面', 0, 0, 300, 30, .99)]


def make_panel_watcher(boxes=(), recognizer=None, on_detected=None, progress=None, on_outcome=None):
    from keyboard_executor.core.sequence_panel_watcher import PanelWatcher
    now, calls = [0.0], []
    win = WindowInfo(1, 'panel-test', 'app', 0, 0, 500, 500, True)
    platform = SimpleNamespace(screen_capture=FakeScreenCapture(np.zeros((300, 400, 3), np.uint8)),
        window_manager=FakeWindowManager([win]), ocr_engine=FakeOcrEngine(list(boxes)))
    def recognize(samples, **kwargs):
        calls.extend(samples)
        # 字元對應假 vision 的編號：sample N 的影像 stamp 為 N-1，編號 (stamp-1)%3+1。
        return [reading(s.sample_id, 1, 'ABC'[(s.sample_id-2)%3]) for s in samples]
    def vision(image, _recognize):
        sid = int(image[0, 0, 0]) if image.size else 0
        return PanelVision(index=(sid-1)%3+1, input_box=(100, 600, 600, 750),
                           confirm_box=(650, 600, 900, 750), crop=image)
    config = sequence_config_from_dict(dict(enabled=True, mode='panel', panel_region=[0, 0, 400, 300]))
    stop = threading.Event()
    watcher = PanelWatcher(platform, config, recognizer or SimpleNamespace(recognize=recognize),
        stop, progress, clock=lambda: now[0], on_detected=on_detected, vision=vision,
        on_outcome=on_outcome)
    return watcher, platform, win, now, stop, calls


def settle(watcher, check):
    eventually(lambda: (watcher.tick(), check())[1])


def step(watcher, platform, now, stamp):
    before = len(platform.ocr_engine.calls)
    now[0] = stamp
    platform.screen_capture.image = np.full((300, 400, 3), int(stamp)%255, np.uint8)
    settle(watcher, lambda: len(platform.ocr_engine.calls) > before and not watcher._ocr_busy)
