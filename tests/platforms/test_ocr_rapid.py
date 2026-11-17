"""Offline model selection and the RapidOCR -> application boundary."""
import hashlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from keyboard_executor.platforms.base import TextBox
from keyboard_executor.platforms.common import ocr_rapid


@pytest.fixture
def native(monkeypatch, tmp_path):
    payloads = {name: name.encode() for name in ocr_rapid.RAPID_MODEL_FILES}
    for name, data in payloads.items():
        (tmp_path / name).write_bytes(data)
    monkeypatch.setattr(ocr_rapid, "RAPID_MODEL_SHA256", {
        name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()})
    constructions, calls = [], []
    result = SimpleNamespace(
        boxes=np.array([[[3, 5], [42, 4], [44, 19], [2, 20]]]),
        txts=("張景翔[CH-484]>> 呈呈",), scores=(.973,))

    def construct(*, params):
        constructions.append(params)

        def predict(image, *, use_cls):
            calls.append((image, use_cls))
            return result
        return predict

    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(
        RapidOCR=construct, EngineType=SimpleNamespace(ONNXRUNTIME="onnxruntime"),
        OCRVersion=SimpleNamespace(PPOCRV6="PP-OCRv6"),
        ModelType=SimpleNamespace(TINY="tiny")))
    return tmp_path, constructions, calls, result


def test_lazy_engine_uses_local_tiny_onnx_and_preserves_raw_text_and_geometry(native):
    folder, constructions, calls, _ = native
    engine = ocr_rapid.RapidOcrEngine(model_dir=folder)
    assert constructions == []
    image = np.zeros((24, 80, 3), dtype=np.uint8)
    expected = [TextBox("張景翔[CH-484]>> 呈呈", 2, 4, 42, 16, .973)]
    assert engine.recognize(image) == expected
    assert engine.recognize(image) == expected
    assert len(constructions) == 1
    assert all(frame is image and use_cls is False for frame, use_cls in calls)
    params = constructions[0]
    for task, filename in zip(("Det", "Rec", "Cls"), ocr_rapid.RAPID_MODEL_FILES):
        assert params[f"{task}.model_path"] == str(folder / filename)
    for task in ("Det", "Rec"):
        assert params[f"{task}.engine_type"] == "onnxruntime"
        assert params[f"{task}.ocr_version"] == "PP-OCRv6"
        assert params[f"{task}.model_type"] == "tiny"
    assert params["Global.use_cls"] is False
    assert params["Global.text_score"] == 0
    assert params["Rec.rec_batch_num"] == 1
    assert params["EngineConfig.onnxruntime.intra_op_num_threads"] == 2


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_bad_local_models_fail_before_native_constructor_can_download(native, damage):
    folder, constructions, _, _ = native
    path = folder / ocr_rapid.RAPID_MODEL_FILES[0]
    original = path.read_bytes()
    path.unlink() if damage == "missing" else path.write_bytes(b"bad model")
    engine = ocr_rapid.RapidOcrEngine(model_dir=folder)
    with pytest.raises((FileNotFoundError, ValueError), match=path.name):
        engine.recognize(np.zeros((24, 80, 3), dtype=np.uint8))
    assert constructions == []
    # Installing/replacing the model permits the next attempt; no poisoned cache.
    path.write_bytes(original)
    assert engine.recognize(np.zeros((24, 80, 3), dtype=np.uint8))


def test_no_text_is_empty_not_an_exception(native):
    folder, _, _, result = native
    result.boxes = result.txts = result.scores = None
    assert ocr_rapid.RapidOcrEngine(model_dir=folder).recognize(
        np.zeros((24, 80, 3), dtype=np.uint8)) == []


def test_frozen_model_dir_uses_bundle_instead_of_user_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert ocr_rapid.default_model_dir() == tmp_path / "ocr_models"


def test_source_model_dir_uses_dedicated_user_cache(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(ocr_rapid.Path, "home", lambda: tmp_path)
    assert ocr_rapid.default_model_dir() == tmp_path / ".keyboard-executor/models/chat-ocr-v6-tiny"
