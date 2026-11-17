"""實跑模型準備與 spec 決策；不下載模型、不執行 PyInstaller Analysis。"""
from __future__ import annotations

import hashlib
import fnmatch
import importlib.util
import io
import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODEL_BYTES = {
    "PP-OCRv6_det_tiny.onnx": b"detector fixture",
    "PP-OCRv6_rec_tiny.onnx": b"recognizer fixture",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx": b"classifier fixture",
}


@pytest.fixture
def models(monkeypatch, tmp_path):
    """隔離真正的大模型；保留共享模型契約與真實檔案雜湊驗證。"""
    module = ModuleType("keyboard_executor.platforms.common.ocr_rapid")
    module.BUNDLED_RAPID_MODELS_DIRNAME = "ocr_models"
    module.RAPID_MODEL_FILES = tuple(MODEL_BYTES)
    module.RAPID_MODEL_SHA256 = {
        name: hashlib.sha256(data).hexdigest() for name, data in MODEL_BYTES.items()
    }
    module.RAPID_MODEL_URLS = {
        name: f"https://models.example/{name}" for name in MODEL_BYTES
    }
    module.default_model_dir = lambda: tmp_path / "chat-models"
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    return module


def load_preparer():
    path = ROOT / "packaging" / "prepare_chat_ocr_models.py"
    assert path.is_file(), "缺少顯式模型準備工具"
    spec = importlib.util.spec_from_file_location("chat_model_preparer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_models(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in MODEL_BYTES.items():
        (directory / name).write_bytes(data)


def test_prepare_reuses_verified_cache_without_network(models, monkeypatch):
    write_models(models.default_model_dir())
    preparer = load_preparer()
    monkeypatch.setattr(preparer.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("已有快取不應連網"))

    paths = preparer.prepare_models()

    assert {path.name: path.read_bytes() for path in paths} == MODEL_BYTES


def test_prepare_copies_local_models_and_only_publishes_verified_files(models, tmp_path, monkeypatch):
    source = tmp_path / "source"
    write_models(source)
    preparer = load_preparer()
    real_replace = preparer.os.replace
    published = []

    def replace_verified(source_file, destination):
        source_file, destination = Path(source_file), Path(destination)
        assert source_file.parent == destination.parent
        assert not destination.exists()
        assert source_file.read_bytes() == MODEL_BYTES[destination.name]
        published.append(destination.name)
        return real_replace(source_file, destination)

    monkeypatch.setattr(preparer.os, "replace", replace_verified)
    paths = preparer.prepare_models(source_dir=source)

    assert {path.name: path.read_bytes() for path in paths} == MODEL_BYTES
    assert set(published) == set(MODEL_BYTES)
    assert {path.name for path in models.default_model_dir().iterdir()} == set(MODEL_BYTES)


def test_prepare_downloads_to_explicit_destination(models, tmp_path, monkeypatch):
    preparer = load_preparer()
    monkeypatch.setattr(
        preparer.urllib.request, "urlopen",
        lambda url, **_kwargs: io.BytesIO(MODEL_BYTES[url.rsplit("/", 1)[-1]]),
    )
    destination = tmp_path / "explicit-models"

    paths = preparer.prepare_models(destination=destination)

    assert {path.name: path.read_bytes() for path in paths} == MODEL_BYTES
    assert all(path.parent == destination for path in paths)


@pytest.mark.parametrize("failure", ["hash", "missing"])
def test_prepare_rejects_invalid_local_source_without_partial_file(models, tmp_path, failure):
    source = tmp_path / "source"
    source.mkdir()
    filename = "PP-OCRv6_det_tiny.onnx"
    if failure == "hash":
        (source / filename).write_bytes(b"corrupt")
    preparer = load_preparer()

    with pytest.raises((ValueError, FileNotFoundError), match=filename):
        preparer.prepare_models(source_dir=source)

    assert list(models.default_model_dir().iterdir()) == []


def test_prepare_rejects_bad_cache_without_overwriting_it(models):
    destination = models.default_model_dir()
    write_models(destination)
    broken = destination / "PP-OCRv6_det_tiny.onnx"
    broken.write_bytes(b"keep diagnostic evidence")
    preparer = load_preparer()

    with pytest.raises(ValueError, match="SHA256"):
        preparer.prepare_models()

    assert broken.read_bytes() == b"keep diagnostic evidence"


@pytest.mark.parametrize("failure", ["hash", "interrupted"])
def test_prepare_cleans_failed_download(models, monkeypatch, failure):
    preparer = load_preparer()

    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError("connection interrupted")
            return super().read(size)

    response = io.BytesIO(b"bad model") if failure == "hash" else Interrupted(b"partial")
    monkeypatch.setattr(preparer.urllib.request, "urlopen", lambda *_a, **_k: response)

    with pytest.raises((ValueError, OSError)):
        preparer.prepare_models()

    assert list(models.default_model_dir().iterdir()) == []


def test_prepare_cli_reports_error_and_nonzero_status(models, tmp_path, capsys):
    preparer = load_preparer()

    assert preparer.main(["--source-dir", str(tmp_path / "missing")]) == 1
    assert "PP-OCRv6_det_tiny.onnx" in capsys.readouterr().err


def run_packaging_spec(monkeypatch, tmp_path):
    """執行真實 spec，僅替換會啟動建置或讀全環境的 PyInstaller hooks。"""
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    hooks = ModuleType("PyInstaller.utils.hooks")
    def collect_data_files(package, *, includes=None):
        candidates = ("config.yaml", "default_models.yaml", "models/unused-small.onnx")
        return [
            (f"{package}/{name}", package)
            for name in candidates
            if includes is None or any(fnmatch.fnmatch(name, pattern) for pattern in includes)
        ]

    hooks.collect_data_files = collect_data_files
    hooks.collect_dynamic_libs = lambda package: [(f"{package}/native.dll", package)]
    hooks.collect_submodules = lambda package, **_kwargs: [package]
    hooks.copy_metadata = lambda package: [(f"{package}.dist-info", f"{package}.dist-info")]
    monkeypatch.setitem(sys.modules, hooks.__name__, hooks)
    monkeypatch.setattr("importlib.metadata.distributions", lambda: [])

    def analysis(_scripts, **kwargs):
        return SimpleNamespace(**kwargs, pure=[], scripts=[])

    return runpy.run_path(str(ROOT / "packaging" / "keyboard-executor.spec"), init_globals={
        "SPECPATH": str(ROOT / "packaging"),
        "Analysis": analysis,
        "PYZ": lambda *_args: None,
        "EXE": lambda *_args, **kwargs: SimpleNamespace(**kwargs),
        "COLLECT": lambda *_args, **_kwargs: None,
        "BUNDLE": lambda *_args, **kwargs: SimpleNamespace(**kwargs),
    })


def test_spec_omits_old_engine_weights_and_runtime_dependencies(models, monkeypatch, tmp_path):
    write_models(models.default_model_dir())
    analysis = run_packaging_spec(monkeypatch, tmp_path)['a']
    assert not any('paddle' in str(entry).lower() for entry in analysis.datas + analysis.binaries)
    assert not any(name in {'paddle', 'paddleocr', 'paddlex'} for name in analysis.hiddenimports)
    assert {'paddle', 'paddleocr', 'paddlex'} <= set(analysis.excludes)
    assert any(str(src).startswith('opencc/') for src, _ in analysis.datas)


def test_spec_collects_verified_chat_models_and_onnx_runtime(models, monkeypatch, tmp_path):
    write_models(models.default_model_dir())

    analysis = run_packaging_spec(monkeypatch, tmp_path)["a"]

    bundled = {Path(src).name for src, destination in analysis.datas if destination == "ocr_models"}
    assert bundled == set(MODEL_BYTES)
    assert ("rapidocr/config.yaml", "rapidocr") in analysis.datas
    assert ("rapidocr/default_models.yaml", "rapidocr") in analysis.datas
    assert ("rapidocr/models/unused-small.onnx", "rapidocr") not in analysis.datas
    assert ("rapidocr.dist-info", "rapidocr.dist-info") in analysis.datas
    assert ("onnxruntime.dist-info", "onnxruntime.dist-info") in analysis.datas
    assert ("onnxruntime/native.dll", "onnxruntime") in analysis.binaries
    assert "rapidocr.main" in analysis.hiddenimports
    assert "rapidocr.inference_engine.onnxruntime" in analysis.hiddenimports
    assert "onnxruntime" in analysis.hiddenimports
    assert "rapidocr" not in analysis.excludes
    assert "openvino" in analysis.excludes
    assert "torch" in analysis.excludes


def test_mac_spec_targets_arm64_and_passes_signing_and_keychain_settings(models, monkeypatch, tmp_path):
    write_models(models.default_model_dir())
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("CODESIGN_IDENTITY", "Developer ID Application: Test (EXAMPLE)")
    result = run_packaging_spec(monkeypatch, tmp_path)
    assert result["exe"].target_arch == "arm64"
    assert result["exe"].codesign_identity == "Developer ID Application: Test (EXAMPLE)"
    assert Path(result["exe"].entitlements_file).name == "entitlements.plist"
    assert result["app"].info_plist["LSMinimumSystemVersion"] == "14.0"
    assert "keyring.backends.macOS" in result["a"].hiddenimports
    assert "mss.darwin" in result["a"].hiddenimports


@pytest.mark.parametrize("failure", ["hash", "missing"])
def test_spec_stops_build_for_unverified_chat_models(models, monkeypatch, tmp_path, failure):
    write_models(models.default_model_dir())
    broken = models.default_model_dir() / "PP-OCRv6_det_tiny.onnx"
    if failure == "hash":
        broken.write_bytes(b"corrupt")
    else:
        broken.unlink()

    with pytest.raises(SystemExit, match="PP-OCRv6_det_tiny.onnx"):
        run_packaging_spec(monkeypatch, tmp_path)
