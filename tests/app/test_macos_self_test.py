import importlib.util
from pathlib import Path
import sys

import pytest

from keyboard_executor.app import self_test


def test_mac_self_test_checks_native_dynamic_backends(monkeypatch):
    path = Path(self_test.__file__)
    spec = importlib.util.spec_from_file_location("mac_self_test_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "darwin")
        spec.loader.exec_module(module)
    assert {"pynput.keyboard._darwin", "pynput.mouse._darwin", "mss.darwin",
            "ApplicationServices", "Quartz", "keyring.backends.macOS"} <= set(module.DEFAULT_MODULES)


def test_self_test_fails_if_ocr_cannot_recognize_the_smoke_image(monkeypatch):
    from keyboard_executor.platforms.common import ocr_rapid
    from keyboard_executor.platforms.common import ocr_process
    class EmptyOcr:
        def _load(self):
            return None
        def recognize(self, image):
            return []
        def close(self):
            pass
    monkeypatch.setattr(ocr_rapid, "RapidOcrEngine", EmptyOcr)
    monkeypatch.setattr(ocr_process, "ProcessOcrEngine", lambda *args: EmptyOcr())
    with pytest.raises(RuntimeError, match="OCR"):
        self_test._default_load_ocr()


def test_self_test_exercises_ocr_process_and_closes_it(monkeypatch):
    from keyboard_executor.platforms.common import ocr_rapid, ocr_process
    closed = []
    class Process:
        def recognize(self, image):
            assert image.shape == (160, 640, 3)
            return ["recognized smoke text"]
        def close(self):
            closed.append(True)
    monkeypatch.setattr(ocr_process, "ProcessOcrEngine", lambda *args: Process())
    monkeypatch.setattr(ocr_rapid, "RapidOcrEngine", lambda: pytest.fail("必須檢查 OCR 子程序介面"))
    self_test._default_load_ocr()
    assert closed == [True]
