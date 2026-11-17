"""發布前自我檢查（KeyboardExecutor.exe --self-test）。

打包壞掉的版本一旦發布，朋友的程式開不起來也就無法再自動更新，所以 release.py
上傳前先用這個檢查：載入打包時容易漏掉的動態模組、驗證 OCR 模型、離屏建立主視窗。"""
from __future__ import annotations

import importlib
import sys
import tempfile
import traceback

if sys.platform == "win32":
    DEFAULT_MODULES = ("numpy", "cv2", "mss", "mss.windows", "pynput.keyboard._win32",
                       "pynput.mouse._win32", "pydirectinput", "onnxruntime",
                       "rapidocr.main", "opencc")
elif sys.platform == "darwin":
    DEFAULT_MODULES = ("numpy", "cv2", "mss", "mss.darwin", "pynput.keyboard._darwin",
                       "pynput.mouse._darwin", "ApplicationServices", "Quartz",
                       "keyring.backends.macOS", "onnxruntime", "rapidocr.main", "opencc")
else:
    DEFAULT_MODULES = ("numpy", "cv2", "mss", "onnxruntime", "rapidocr.main", "opencc")


def _default_build(data_dir):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from keyboard_executor.app.application import build_app
    return build_app(data_dir=data_dir, permission_checks={}, request_permissions=lambda: None)


def _default_load_ocr() -> None:
    import cv2
    import numpy as np
    import threading
    from keyboard_executor.platforms.common.ocr_process import ProcessOcrEngine
    image = np.full((160, 640, 3), 255, dtype=np.uint8)
    cv2.putText(image, "TEST123", (20, 110), cv2.FONT_HERSHEY_SIMPLEX,
                2.5, (0, 0, 0), 4, cv2.LINE_AA)
    # 與正式功能相同的 spawn 路徑，讓 frozen .app 漏 freeze_support、子程序
    # 匯入或模型載入失敗時也會擋住發布，而不只是測試主程序能載入模型。
    engine = ProcessOcrEngine(None, threading.Event())
    try:
        if not engine.recognize(image):
            raise RuntimeError("OCR 自我檢查未辨識出測試文字")
    finally:
        engine.close()


def run_self_test(*, build=None, load_ocr=None, modules=DEFAULT_MODULES) -> int:
    build = build or _default_build
    load_ocr = load_ocr or _default_load_ocr
    try:
        for name in modules:
            importlib.import_module(name)
        load_ocr()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as data_dir:
            _app, window = build(data_dir=data_dir)
            window.close()
    except Exception as e:
        print(f"自我檢查失敗：{e}", flush=True)
        traceback.print_exc()
        return 1
    print("自我檢查通過", flush=True)
    return 0
