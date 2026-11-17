"""Shared offline PP-OCRv6 tiny/ONNX adapter for every OCR entry point.

Native imports and model loading happen on the first recognition in the OCR
worker. Models must already be bundled or explicitly prepared; recognition
never downloads missing assets or silently switches to another model.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import sys
import threading

from keyboard_executor.platforms.base import OcrEngine, OcrRecognitionError, TextBox

BUNDLED_RAPID_MODELS_DIRNAME = "ocr_models"
RAPID_MODEL_FILES = (
    "PP-OCRv6_det_tiny.onnx",
    "PP-OCRv6_rec_tiny.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
)
RAPID_MODEL_SHA256 = dict(zip(RAPID_MODEL_FILES, (
    "f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5",
    "e16e242de5937ad92609223f19bc2aff3727ee40b095f996907c24749bad251b",
    "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
)))
_MODEL_ROOT_URL = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx"
RAPID_MODEL_URLS = dict(zip(RAPID_MODEL_FILES, (
    f"{_MODEL_ROOT_URL}/PP-OCRv6/det/{RAPID_MODEL_FILES[0]}",
    f"{_MODEL_ROOT_URL}/PP-OCRv6/rec/{RAPID_MODEL_FILES[1]}",
    f"{_MODEL_ROOT_URL}/PP-OCRv4/cls/{RAPID_MODEL_FILES[2]}",
)))
logger = logging.getLogger(__name__)


def default_model_dir() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / BUNDLED_RAPID_MODELS_DIRNAME
    # Keep the existing v6 cache location; migration never deletes user assets.
    return Path.home() / ".keyboard-executor/models/chat-ocr-v6-tiny"


class RapidOcrEngine(OcrEngine):
    def __init__(self, *, model_dir: Path | None = None):
        self._model_dir = Path(model_dir) if model_dir is not None else default_model_dir()
        self._engine = None
        self._lock = threading.Lock()

    def _load(self):
        # Check all assets before RapidOCR can try its own download fallback.
        # Its constructor also loads the classifier even when use_cls=False.
        for name in RAPID_MODEL_FILES:
            path = self._model_dir / name
            if not path.is_file():
                raise FileNotFoundError(f"OCR 模型不存在: {path}; 請重新安裝完整版本或執行模型準備工具")
            if hashlib.sha256(path.read_bytes()).hexdigest() != RAPID_MODEL_SHA256[name]:
                raise ValueError(f"OCR 模型驗證失敗: {path}; 請重新安裝完整版本")

        from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR

        params = {
            "Global.log_level": "warning",
            "Global.use_cls": False,
            "Global.text_score": 0.0,  # Each consumer applies its own confidence gate.
            "Global.width_height_ratio": -1,
            "Global.min_height": 1,
            "Global.min_side_len": 1,
            "Global.max_side_len": 4000,
            "Global.model_root_dir": str(self._model_dir),
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Cls.engine_type": EngineType.ONNXRUNTIME,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Det.model_type": ModelType.TINY,
            "Rec.model_type": ModelType.TINY,
            "Det.model_path": str(self._model_dir / RAPID_MODEL_FILES[0]),
            "Rec.model_path": str(self._model_dir / RAPID_MODEL_FILES[1]),
            "Cls.model_path": str(self._model_dir / RAPID_MODEL_FILES[2]),
            "Det.limit_type": "min",
            "Det.limit_side_len": 64,
            "Det.box_thresh": .6,
            "Det.unclip_ratio": 1.5,
            "Det.use_dilation": False,
            "Det.mean": [.5, .5, .5],
            "Det.std": [.5, .5, .5],
            "Rec.rec_batch_num": 1,
        }
        engine = RapidOCR(params=params)
        logger.info("OCR: PP-OCRv6 tiny + ONNX Runtime（所有功能共用的離線模型）")
        return engine

    def recognize(self, image) -> list[TextBox]:
        with self._lock:
            if self._engine is None:
                self._engine = self._load()
            try:
                result = self._engine(image, use_cls=False)
            except Exception as exc:
                raise OcrRecognitionError(f'OCR 推論失敗：{exc}') from exc
        if result.boxes is None or result.txts is None:
            return []
        boxes = []
        for polygon, text, score in zip(result.boxes, result.txts, result.scores):
            x, y = polygon.min(axis=0)
            right, bottom = polygon.max(axis=0)
            boxes.append(TextBox(text, int(x), int(y), int(right - x),
                                 int(bottom - y), float(score)))
        return boxes
