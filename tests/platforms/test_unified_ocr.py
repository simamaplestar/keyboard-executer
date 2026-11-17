"""All OCR consumers use the same offline v6 adapter, without Paddle fallback."""
from types import SimpleNamespace
import sys

import numpy as np
import pytest

from keyboard_executor.platforms.base import TextBox
from keyboard_executor.platforms.common import ocr_process, ocr_rapid
from keyboard_executor.platforms.factory import get_platform


def test_native_factory_always_selects_rapid_for_legacy_language_values():
    if sys.platform not in {'win32', 'darwin'}:
        pytest.skip('native factory test')
    for lang in (None, 'ch', 'en', 'japan', 'chinese_cht'):
        engine = get_platform(ocr_lang=lang).ocr_engine
        assert type(engine).__module__ == ocr_rapid.__name__
        assert type(engine).__name__ == 'RapidOcrEngine'
        assert engine._engine is None, 'constructing platform must not load models'


def test_process_worker_uses_one_rapid_instance_for_every_image(monkeypatch):
    created, received, messages = [], [], []
    class Engine:
        def __init__(self):
            created.append(self)
        def recognize(self, image):
            received.append(image)
            return [TextBox('请按照號碼順序输入文字。', 0, 0, 200, 20, .97)]
    def old_engine(*args, **kwargs):
        raise AssertionError('old Paddle route is still in use')
    monkeypatch.setattr(ocr_rapid, 'RapidOcrEngine', Engine, raising=False)
    monkeypatch.setitem(sys.modules, 'keyboard_executor.platforms.common.ocr_paddle',
                        SimpleNamespace(PaddleOcrEngine=old_engine))
    pictures = [np.zeros((4, 4, 3), np.uint8), np.ones((4, 4, 3), np.uint8)]
    iterator = iter(pictures)
    def receive():
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError()
    connection = SimpleNamespace(send=messages.append, recv=receive, close=lambda: None)
    ocr_process._serve(connection, 'japan')  # legacy language no longer selects models
    assert len(created) == 1
    assert len(received) == 2
    assert all(actual is expected for actual, expected in zip(received, pictures))
    assert messages[0] == (True, None)
    assert all(ok and boxes[0].text == '请按照號碼順序输入文字。' for ok, boxes in messages[1:])
