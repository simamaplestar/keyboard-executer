import os
from pathlib import Path

import pytest

from keyboard_executor.core.update import install as inst
from keyboard_executor.core.update.download import staged_path, version_marker
from keyboard_executor.core.update.install import (
    cleanup_after_update, install_staged, old_path, restart_command, restart_env,
)
from keyboard_executor.core.update.release import UpdateError


def setup_exe(folder: Path, name="KeyboardExecutor.exe") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / name
    exe.write_bytes(b"old")
    staged_path(exe).write_bytes(b"new")
    version_marker(exe).write_text("0.6.0", encoding="utf-8")
    return exe


def test_install_swaps_files(tmp_path):
    exe = setup_exe(tmp_path)
    install_staged(exe)
    assert exe.read_bytes() == b"new"
    assert old_path(exe).read_bytes() == b"old"
    assert not staged_path(exe).exists()
    assert not version_marker(exe).exists()


def test_install_replaces_previous_old(tmp_path):
    exe = setup_exe(tmp_path)
    old_path(exe).write_bytes(b"older")
    install_staged(exe)
    assert old_path(exe).read_bytes() == b"old"


def test_install_rolls_back_when_new_cannot_move(tmp_path, monkeypatch):
    exe = setup_exe(tmp_path)
    monkeypatch.setattr(inst.time, "sleep", lambda s: None)

    def rename(src, dst):
        if Path(src) == staged_path(exe):       # 新檔持續被防毒鎖住（重試也沒用）
            raise PermissionError("locked by antivirus")
        os.replace(src, dst)

    with pytest.raises(UpdateError, match="locked by antivirus"):
        install_staged(exe, rename=rename)
    assert exe.read_bytes() == b"old"
    assert staged_path(exe).read_bytes() == b"new"


def test_install_fails_cleanly_when_old_cannot_be_removed(tmp_path, monkeypatch):
    exe = setup_exe(tmp_path)
    old_path(exe).write_bytes(b"older")
    real_unlink = Path.unlink

    def unlink(self, *a, **k):
        if self == old_path(exe):
            raise PermissionError("in use")
        return real_unlink(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(UpdateError, match="使用中"):
        install_staged(exe)
    assert exe.read_bytes() == b"old"
    assert staged_path(exe).read_bytes() == b"new"


def test_install_without_staged_raises(tmp_path):
    exe = tmp_path / "KeyboardExecutor.exe"
    exe.write_bytes(b"old")
    with pytest.raises(UpdateError):
        install_staged(exe)
    assert exe.read_bytes() == b"old"


def test_install_keeps_renamed_exe_name(tmp_path):
    exe = setup_exe(tmp_path / "遊戲 工具", name="我的 KE.exe")
    install_staged(exe)
    assert exe.read_bytes() == b"new"
    assert exe.name == "我的 KE.exe"


def test_restart_command_keeps_args(tmp_path):
    exe = tmp_path / "KE.exe"
    assert restart_command(exe, ["x.exe", "--dir", "D:\\s"]) == [str(exe), "--dir", "D:\\s"]


def test_restart_env_resets_pyinstaller():
    base = {"PATH": "p"}
    env = restart_env(base)
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert env["PATH"] == "p"
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in base


def test_cleanup_removes_old(tmp_path):
    exe = setup_exe(tmp_path)
    old_path(exe).write_bytes(b"old")
    cleanup_after_update(exe)
    assert not old_path(exe).exists()


def test_cleanup_ignores_locked_old(tmp_path, monkeypatch):
    exe = setup_exe(tmp_path)
    old_path(exe).write_bytes(b"old")

    def unlink(self, *a, **k):
        raise PermissionError("in use")
    monkeypatch.setattr(Path, "unlink", unlink)
    cleanup_after_update(exe)          # 不拋例外
    assert old_path(exe).exists()
    assert inst  # 模組可匯入


def test_install_retries_transient_lock(tmp_path, monkeypatch):
    exe = setup_exe(tmp_path)
    attempts = {"n": 0}

    def rename(src, dst):
        if Path(src) == staged_path(exe):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise PermissionError("scanning")
        os.replace(src, dst)
    monkeypatch.setattr(inst.time, "sleep", lambda s: None)
    install_staged(exe, rename=rename)
    assert exe.read_bytes() == b"new" and attempts["n"] == 3
