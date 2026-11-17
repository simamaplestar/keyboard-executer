"""執行建置腳本驗證失敗傳遞及產物順序；工具替身不執行真正的簽章或打包。"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class HostRequirements(unittest.TestCase):
    def validate(self, **changes):
        spec = importlib.util.spec_from_file_location("macos_support", ROOT / "packaging/macos_support.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        values = dict(platform_name="darwin", machine="arm64", mac_version="14.0", python_version=(3, 11))
        values.update(changes)
        return module.validate_host(**values)

    def test_accepts_apple_silicon_on_supported_os_and_python(self):
        self.validate()
        self.validate(mac_version="26.1", python_version=(3, 14))

    def test_rejects_linux_windows_intel_rosetta_old_os_and_python(self):
        for changes in [dict(platform_name="linux"), dict(platform_name="win32"),
                        dict(machine="x86_64"), dict(mac_version="13.7"),
                        dict(mac_version=""), dict(python_version=(3, 10))]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(**changes)


STUB = '''import json, os, pathlib, sys
tool = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['BUILD_TRACE'], 'a') as log:
    log.write(json.dumps({'tool': tool, 'args': args}) + '\\n')
stage = tool
if tool == 'build-python':
    if args and args[0].endswith('macos_support.py'):
        stage = 'host'
    elif args and args[0].endswith('prepare_chat_ocr_models.py'):
        stage = 'models'
    elif args[:2] == ['-m', 'PyInstaller']:
        stage = 'build'
        if os.environ.get('FAIL_STAGE') != stage:
            dist = pathlib.Path(args[args.index('--distpath') + 1])
            exe = dist / 'KeyboardExecutor.app/Contents/MacOS/KeyboardExecutor'
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_text('#!/bin/sh\\nexit ' + os.environ.get('SELF_TEST_EXIT', '0') + '\\n')
            exe.chmod(0o755)
if stage == os.environ.get('FAIL_STAGE'):
    sys.exit(9)
if tool == 'ditto':
    pathlib.Path(args[-1]).write_bytes(b'test zip')
if tool == 'shasum':
    print('0' * 64 + '  ' + args[-1])
'''


@unittest.skipIf(os.name == "nt", "shell 建置行為於 Unix runner 驗證")
class BuildScript(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mac build ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packaging = self.root / "project with spaces/packaging"
        self.packaging.mkdir(parents=True)
        shutil.copy2(ROOT / "packaging/build.sh", self.packaging / "build.sh")
        self.tools = self.root / "fake tools"
        self.tools.mkdir()
        for tool in ("build-python", "codesign", "ditto", "shasum"):
            path = self.tools / tool
            path.write_text(f"#!{sys.executable}\n" + STUB)
            path.chmod(0o755)
        self.trace = self.root / "trace.jsonl"
        self.env = dict(os.environ, PATH=f"{self.tools}{os.pathsep}{os.environ['PATH']}",
                        PYTHON=str(self.tools / "build-python"), BUILD_TRACE=str(self.trace),
                        KE_DIST_DIR=str(self.root / "dist with spaces"),
                        KE_WORK_DIR=str(self.root / "build with spaces"))

    def run_build(self, **changes):
        return subprocess.run(["bash", str(self.packaging / "build.sh")],
                              cwd=self.root, env=dict(self.env, **changes),
                              capture_output=True, text=True, timeout=20)

    def calls(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def test_build_prepares_models_and_verifies_before_creating_zip(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertTrue(calls[0]['args'][0].endswith('macos_support.py'))
        self.assertTrue(calls[1]['args'][0].endswith('prepare_chat_ocr_models.py'))
        self.assertEqual(calls[2]['args'][:2], ['-m', 'PyInstaller'])
        self.assertEqual([call['tool'] for call in calls[3:]], ['codesign', 'ditto', 'shasum'])
        self.assertIn('--verify', calls[3]['args'])
        self.assertIn('--keepParent', calls[4]['args'])
        self.assertTrue((Path(self.env['KE_DIST_DIR']) / 'KeyboardExecutor-macos-arm64.zip.sha256').is_file())

    def test_any_build_or_verification_failure_does_not_create_release_archive(self):
        for stage in ('host', 'models', 'build', 'codesign'):
            with self.subTest(stage=stage):
                result = self.run_build(FAIL_STAGE=stage)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(any(call['tool'] == 'ditto' for call in self.calls()))
                self.trace.unlink(missing_ok=True)

    def test_failed_bundled_self_test_does_not_create_archive(self):
        result = self.run_build(SELF_TEST_EXIT='7')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call['tool'] == 'ditto' for call in self.calls()))

    def test_success_then_failed_rebuild_removes_stale_release_files(self):
        for stage in ('models', 'build', 'codesign', 'self-test', 'ditto', 'shasum'):
            with self.subTest(stage=stage):
                result = self.run_build()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                archive = Path(self.env['KE_DIST_DIR']) / 'KeyboardExecutor-macos-arm64.zip'
                checksum = archive.with_suffix('.zip.sha256')
                self.assertTrue(archive.exists())
                self.assertTrue(checksum.exists())
                changes = {'SELF_TEST_EXIT': '7'} if stage == 'self-test' else {'FAIL_STAGE': stage}
                result = self.run_build(**changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(archive.exists())
                self.assertFalse(checksum.exists())
                self.assertFalse(list(archive.parent.glob('.archive.*')))

    def test_offline_model_source_is_one_argument(self):
        source = str(self.root / 'offline models')
        result = self.run_build(OCR_SOURCE_DIR=source)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls()[1]['args'][-2:], ['--source-dir', source])
