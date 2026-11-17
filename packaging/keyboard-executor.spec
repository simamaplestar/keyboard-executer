# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller：Windows onefile exe／macOS .app，共用離線 v6 tiny OCR。

    cd packaging && python -m PyInstaller --clean --noconfirm keyboard-executor.spec

所有 OCR 使用 RapidOCR + ONNX Runtime；prepare_chat_ocr_models.py 沿用既有
工具名稱，負責顯式準備同一組 v6 模型。建置驗 SHA256 後收進 ocr_models/，
不收舊引擎或其權重，也不依賴使用者首次執行連網下載。
此處為建置期腳本，因此可依 sys.platform 選擇打包格式。
"""
import hashlib
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

ROOT = Path(SPECPATH).parent            # SPECPATH 由 PyInstaller 注入＝本檔所在目錄
sys.path.insert(0, str(ROOT / "src"))
from keyboard_executor import __version__  # noqa: E402  版本單一來源（與 pyproject 同步）
# 模型目錄名與模型名直接向 runtime 取，避免兩邊各寫一份字串而悄悄走鐘。
from keyboard_executor.platforms.common.ocr_rapid import (  # noqa: E402
    BUNDLED_RAPID_MODELS_DIRNAME,
    RAPID_MODEL_FILES,
    RAPID_MODEL_SHA256,
    default_model_dir,
)

APP_NAME = "KeyboardExecutor"
BUNDLE_ID = "io.github.simamaplestar.keyboardexecutor"

# pynput / mss 以動態 import 載入平台後端，PyInstaller 靜態分析看不到，需明列。
# （測試 sanity 斷言兩平台鍵名都在本檔：pynput.keyboard._darwin / pynput.keyboard._win32）
if sys.platform == "darwin":
    platform_hiddenimports = [
        "pynput.keyboard._darwin", "pynput.mouse._darwin",
        "mss.darwin",
        "ApplicationServices", "Quartz", "AppKit",
        "keyring.backends.macOS", "keyring.backends.macOS.api",
    ]
else:  # win32
    platform_hiddenimports = [
        "pynput.keyboard._win32", "pynput.mouse._win32",
        "mss.windows",
        "pydirectinput",
    ]

# 僅收實際使用的 runtime 資料，不掃入建置環境全部套件 metadata。
datas = collect_data_files('opencc')
if sys.platform == "darwin":
    datas += copy_metadata("keyring")
binaries = []

# RapidOCR 的主類別由 __getattr__ 延遲載入，須明列 main；只用 ONNX Runtime。
# 精確收兩份 YAML，避免把套件目錄中自動下載的其他模型一起打包。
datas += collect_data_files("rapidocr", includes=["config.yaml", "default_models.yaml"])
for _package in ("rapidocr", "onnxruntime", "opencc-python-reimplemented"):
    datas += copy_metadata(_package)
binaries += collect_dynamic_libs("onnxruntime")
rapid_hiddenimports = [
    "rapidocr.main", "rapidocr.inference_engine.onnxruntime",
    "onnxruntime", "onnxruntime.capi.onnxruntime_pybind11_state",
]
_RAPID_UNUSED_BACKENDS = [
    f"rapidocr.inference_engine.{_backend}"
    for _backend in ("openvino", "paddle", "pytorch", "tensorrt", "mnn")
]

# 建置不連網、不自動修復：模型必須與 runtime 的固定 SHA256 完全一致。
for _filename in RAPID_MODEL_FILES:
    _model_path = default_model_dir() / _filename
    if not _model_path.is_file():
        raise SystemExit(
            f"[spec] 找不到 OCR 模型：{_model_path}\n"
            "       請先執行 python packaging/prepare_chat_ocr_models.py，再重新打包。"
        )
    with _model_path.open("rb") as _model_file:
        _digest = hashlib.file_digest(_model_file, "sha256").hexdigest()
    if _digest != RAPID_MODEL_SHA256[_filename]:
        raise SystemExit(
            f"[spec] OCR 模型 SHA256 不符：{_model_path}\n"
            "       請移除錯誤檔案並重新執行 packaging/prepare_chat_ocr_models.py。"
        )
    datas += [(str(_model_path), BUNDLED_RAPID_MODELS_DIRNAME)]

# --- 二進位瘦身 ---
# onefile 的每次啟動成本 ∝ 包體積（bootloader 每次都要解壓全部內容到 %TEMP%），
# 所以剔除確定用不到的大檔。判斷依據皆為「runtime 程式碼不會走到」，逐項註明：
_DROP_BINARY_KEYS = (
    # cv2 只用來做 numpy 影像運算（截圖→OCR），從不讀寫影片檔；這兩顆 ffmpeg 共 56MB。
    "opencv_videoio_ffmpeg",
    # app 只 import QtCore/QtGui/QtWidgets（已用 grep 確認），無任何 QML/Quick 場景；
    # 連帶涵蓋 Qt6QmlModels / Qt6QuickWidgets 等衍生檔，共約 13MB。
    "qt6quick", "qt6qml",
    # 不顯示 PDF，共約 4MB。
    "qt6pdf",
)

common_hiddenimports = collect_submodules('pywinctl') + ['cv2', 'pyclipper', 'psutil']

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=platform_hiddenimports + common_hiddenimports + rapid_hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # 即使建置環境還裝有舊套件，也不能誤收舊引擎或未使用的推論後端。
    excludes=["paddle", "paddleocr", "paddlex", "tkinter", "torch", "tensorflow", "tensorflow_core",
              "openvino", "tensorrt", "MNN", "rapidocr_onnxruntime", "meikiocr"]
             + _RAPID_UNUSED_BACKENDS,
    noarchive=False,
)

def _keep(entry):
    """Analysis 產出的 (dest, src, kind) 三元組是否保留（依 _DROP_BINARY_KEYS 剔除）。"""
    name = Path(entry[0]).name.lower()
    return not any(key in name for key in _DROP_BINARY_KEYS)


_dropped = [e[0] for e in a.binaries if not _keep(e)]
a.binaries = [e for e in a.binaries if _keep(e)]
print(f"[spec] 瘦身剔除 {len(_dropped)} 個二進位檔：{', '.join(sorted(_dropped)) or '(無)'}")

pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # macOS：.app 本來就是目錄結構，維持 onedir + BUNDLE。
    exe = EXE(
        pyz,
        a.scripts,
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        strip=False,
        upx=False,    # UPX 會提高防毒誤報率（spec §14 風險），不使用
        console=False,
        argv_emulation=False,  # Qt 自己處理 App 事件，不啟用 bootloader argv 模擬
        target_arch="arm64",
        codesign_identity=os.environ.get("CODESIGN_IDENTITY") or None,
        entitlements_file=str(ROOT / "packaging" / "entitlements.plist"),
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "Keyboard Executor",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "14.0",
            "LSApplicationCategoryType": "public.app-category.utilities",
            # 「輔助使用／螢幕錄製／輸入監控」三權限屬系統管理的 TCC 對話框，
            # 沒有 Info.plist usage-description 鍵；能穩定出現在系統設定清單，
            # 靠的是固定 bundle identifier ＋ 正式簽章（見 README.md）。
            # Automation（pywinctl 以 AppleScript 查應用程式名稱）則必須提供：
            "NSAppleEventsUsageDescription":
                "Keyboard Executor 需要控制「系統事件」以查詢與切換目標視窗。",
        },
    )
else:
    # Windows：onefile——所有 binaries/datas 併進單一 exe，發布時只需傳這一個檔。
    # runtime_tmpdir=None ＝ 解壓到系統 %TEMP%。注意 PyInstaller 不快取解壓結果，
    # 每次啟動都會重解一次（體積換便攜性的取捨，見本檔開頭）。
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,        # UPX 會提高防毒誤報率（spec §14 風險），不使用
        runtime_tmpdir=None,
        console=False,    # GUI 程式：Windows 不開主控台
    )
