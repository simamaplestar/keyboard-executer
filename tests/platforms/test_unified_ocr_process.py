"""The real process transport hosts one v6 engine; native inference is faked."""
import os
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from keyboard_executor.platforms.base import TextBox
from keyboard_executor.platforms.common.ocr_process import ProcessOcrEngine, _serve
from keyboard_executor.platforms.common.ocr_rapid import RapidOcrEngine
from tests.platforms.test_ocr_rapid import native


def unified_worker(connection, lang):
    class Engine:
        def __init__(self):
            self.calls = 0
        def recognize(self, image):
            assert isinstance(image, np.ndarray)
            self.calls += 1
            if image[0, 0, 0] == 1:
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    pass
            return [TextBox(f'{os.getpid()}:v6:{self.calls}', 1, 2, 3, 4, .99)]
    sys.modules['keyboard_executor.platforms.common.ocr_rapid'] = SimpleNamespace(RapidOcrEngine=Engine)
    _serve(connection, lang)


def picture(value=0):
    return np.full((2, 2, 3), value, np.uint8)


def test_all_requests_share_one_persistent_process_and_engine():
    engine = ProcessOcrEngine('legacy', threading.Event(), worker=unified_worker)
    try:
        rows = [engine.recognize(picture())[0].text.split(':') for _ in range(3)]
        assert len({row[0] for row in rows}) == 1
        assert rows[0][0] != str(os.getpid())
        assert [row[1:] for row in rows] == [['v6', '1'], ['v6', '2'], ['v6', '3']]
    finally:
        engine.close()
        engine._reaper.join(3)
    assert engine._process is None


@pytest.mark.parametrize('operation', ['stop', 'close'])
def test_cancel_remains_fast_and_reaps_busy_child(operation):
    stop = threading.Event()
    engine = ProcessOcrEngine(None, stop, worker=unified_worker)
    engine.recognize(picture())
    errors = []
    def recognize():
        try:
            engine.recognize(picture(1))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=recognize)
    thread.start()
    try:
        time.sleep(.1)
        started = time.monotonic()
        stop.set() if operation == 'stop' else engine.close()
        assert time.monotonic() - started < .3
        thread.join(2)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], InterruptedError)
    finally:
        stop.set()
        engine.close()
        thread.join(3)
        engine._reaper.join(3)
    assert engine._process is None


def test_closed_engine_cannot_restart_worker():
    engine = ProcessOcrEngine(None, threading.Event(), worker=unified_worker)
    engine.close()
    with pytest.raises(InterruptedError):
        engine.recognize(picture())
    engine._reaper.join(2)
    assert engine._process is None


def test_direct_consumers_serialize_native_loading_and_prediction(native, monkeypatch):
    folder, constructions, calls, _ = native
    engine = RapidOcrEngine(model_dir=folder)
    entered, release, second_done = threading.Event(), threading.Event(), threading.Event()
    original_load = engine._load
    def load():
        predict = original_load()
        def blocked(image, **kwargs):
            entered.set()
            assert release.wait(3)
            return predict(image, **kwargs)
        return blocked
    monkeypatch.setattr(engine, '_load', load)
    errors = []
    def recognize(done=None):
        try:
            engine.recognize(picture())
        except BaseException as exc:
            errors.append(exc)
        finally:
            if done:
                done.set()
    first = threading.Thread(target=recognize)
    second = threading.Thread(target=recognize, args=(second_done,))
    first.start()
    try:
        assert entered.wait(2)
        second.start()
        assert not second_done.wait(.1)
        assert len(constructions) == 1
    finally:
        release.set()
        first.join(3)
        if second.ident:
            second.join(3)
    assert not errors
    assert len(calls) == 2
