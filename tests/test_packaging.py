"""打包設定 sanity（M5 Task 5 可測半）。真正的 pyinstaller 建置、簽章、
.app 啟動屬人工驗收（見 packaging/README.md），不在自動化測試假裝驗證。"""
import importlib
import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_entry_points_resolve_to_callables():
    """M4 待辦 #1：pyproject 進入點宣告存在，且指向可 import 的 callable。"""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entries = {**data["project"]["scripts"], **data["project"]["gui-scripts"]}
    assert entries == {"keyboard-executor": "keyboard_executor.cli:main",
                       "keyboard-executor-gui": "keyboard_executor.gui:main"}
    for target in entries.values():
        module_name, func_name = target.split(":")
        module = importlib.import_module(module_name)
        assert callable(getattr(module, func_name))


def test_launcher_module_loads_and_references_gui_main():
    """PyInstaller 進入點與 pip gui-scripts 共用同一個 gui.main。"""
    spec = importlib.util.spec_from_file_location(
        "ke_packaging_launcher", ROOT / "packaging" / "launcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)   # __name__ != "__main__"，不會啟動 GUI
    from keyboard_executor.gui import main
    assert module.main is main


def test_pyinstaller_spec_sanity():
    """spec 檔關鍵內容：進入點、名稱、版本單一來源、bundle id、Automation 用途字串。"""
    text = (ROOT / "packaging" / "keyboard-executor.spec").read_text(encoding="utf-8")
    assert "launcher.py" in text
    assert 'APP_NAME = "KeyboardExecutor"' in text
    assert "from keyboard_executor import __version__" in text
    assert 'BUNDLE_ID = "io.github.simamaplestar.keyboardexecutor"' in text
    assert "NSAppleEventsUsageDescription" in text
    assert "pynput.keyboard._darwin" in text and "pynput.keyboard._win32" in text


def test_spec_builds_windows_onefile():
    """Windows 必須是單檔 exe：需求是「只把一個檔傳給別人就能用」。

    onedir（exclude_binaries=True + COLLECT）的 exe 只是 bootloader，真正的內容在同層
    _internal/，單獨複製走必定啟動失敗——所以 Windows 分支要把 binaries/datas 併進 EXE。
    macOS 仍走 COLLECT + BUNDLE（.app 本來就是目錄）。
    """
    text = (ROOT / "packaging" / "keyboard-executor.spec").read_text(encoding="utf-8")
    windows_branch = text.split("else:")[-1]
    assert "a.binaries," in windows_branch and "a.datas," in windows_branch
    assert "runtime_tmpdir" in windows_branch
    assert "exclude_binaries" not in windows_branch
    # COLLECT/BUNDLE 只該出現在 darwin 分支（rindex：檔案前段另有一個 win32 的 else）
    assert text.index("COLLECT") < text.rindex("else:")
    assert "COLLECT" not in windows_branch and "BUNDLE" not in windows_branch


def test_spec_bundles_ocr_models_for_offline_use():
    """OCR 模型收進包內，且 runtime 找得到同一個目錄名——否則目標機得連網下載。"""
    from keyboard_executor.platforms.common.ocr_rapid import (
        BUNDLED_RAPID_MODELS_DIRNAME, RAPID_MODEL_FILES)

    text = (ROOT / 'packaging' / 'keyboard-executor.spec').read_text(encoding='utf-8')
    assert 'BUNDLED_RAPID_MODELS_DIRNAME' in text
    assert 'RAPID_MODEL_SHA256' in text and 'RAPID_MODEL_FILES' in text
    assert BUNDLED_RAPID_MODELS_DIRNAME == 'ocr_models'
    assert {'PP-OCRv6_det_tiny.onnx', 'PP-OCRv6_rec_tiny.onnx'} <= set(RAPID_MODEL_FILES)


def test_dependencies_have_no_legacy_ocr_runtime():
    deps = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['dependencies']
    assert not any('paddle' in name.lower() for name in deps)
    assert 'rapidocr==3.9.2' in deps
    assert 'onnxruntime==1.30.0' in deps
    assert 'opencc-python-reimplemented==0.1.7' in deps
    assert any(dep.startswith('psutil>=') for dep in deps)  # no longer supplied by the old OCR stack
