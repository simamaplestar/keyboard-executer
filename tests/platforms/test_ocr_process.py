import os
import threading
import time

import numpy as np
import pytest

from keyboard_executor.platforms.base import TextBox
from keyboard_executor.platforms.common.ocr_process import ProcessOcrEngine


def echo_worker(connection, lang):
    connection.send((True, None))
    try:
        while True:
            image = connection.recv()
            if image[0, 0, 0] == 1:
                # 模擬 OCR 長時間持有 GIL，必須只影響子程序。
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    pass
            connection.send((True, [TextBox(f"{lang}:{os.getpid()}", 1, 2, 3, 4, .99)]))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


def test_ocr_runs_in_separate_persistent_process_and_cleans_up():
    engine = ProcessOcrEngine("ch", threading.Event(), worker=echo_worker)
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    try:
        first = engine.recognize(image)
        second = engine.recognize(image)
        assert first == second
        assert first[0].text != f"ch:{os.getpid()}"
        assert first[0].confidence == .99
    finally:
        engine.close()
        engine._reaper.join(3)
    assert not engine._reaper.is_alive()
    assert engine._process is None


def test_stop_during_cpu_bound_ocr_returns_and_reaps_process():
    stop = threading.Event()
    engine = ProcessOcrEngine("ch", stop, worker=echo_worker)
    engine.recognize(np.zeros((2, 2, 3), dtype=np.uint8))
    errors = []

    def recognize():
        try:
            engine.recognize(np.ones((2, 2, 3), dtype=np.uint8))
        except InterruptedError:
            errors.append("cancelled")

    worker = threading.Thread(target=recognize)
    worker.start()
    try:
        # 父程序仍可運作；close 不等待子程序的 10 秒運算。
        stop.wait(.1)
        start = time.monotonic()
        stop.set()
        engine.close()
        assert time.monotonic() - start < .3
        worker.join(2)
        engine._reaper.join(2)
        assert not worker.is_alive()
        assert errors == ["cancelled"]
        assert engine._process is None
    finally:
        stop.set()
        engine.close()
        worker.join(3)


def test_closed_engine_never_starts_child():
    engine = ProcessOcrEngine("ch", threading.Event(), worker=echo_worker)
    engine.close()
    with pytest.raises(InterruptedError):
        engine.recognize(np.zeros((2, 2, 3), dtype=np.uint8))
    engine._reaper.join(2)
    assert engine._process is None
