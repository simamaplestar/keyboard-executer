"""把已驗證的 <exe>.new 換成正在執行的 EXE，並產生重新啟動指令。

Windows 不能覆寫執行中的 EXE，但可以改名：exe → exe.old、exe.new → exe。
任何一步失敗都回到原狀（原 EXE 保持原名、可正常開啟）。"""
from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

from keyboard_executor.core.update.download import staged_path, staged_version, version_marker
from keyboard_executor.core.update.release import UpdateError


def old_path(exe: Path) -> Path:
    return exe.with_name(exe.name + ".old")


def _retry(rename, src: Path, dst: Path, *, attempts: int = 5, delay: float = 0.2) -> None:
    """改名遇到暫時性鎖定（防毒掃描新檔）重試幾次。"""
    for attempt in range(attempts):
        try:
            rename(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def install_staged(exe: Path, *, rename=os.replace) -> None:
    exe = Path(exe)
    new, old = staged_path(exe), old_path(exe)
    if staged_version(exe) is None:
        raise UpdateError("找不到已下載的新版")
    if old.exists():
        try:
            old.unlink()
        except OSError as e:
            raise UpdateError(f"舊版檔案仍被使用中（{old.name}），請關閉其他開著的程式再試: {e}") from e
    try:
        _retry(rename, exe, old)
    except OSError as e:
        raise UpdateError(f"無法移開目前的程式檔: {e}") from e
    try:
        _retry(rename, new, exe)
    except OSError as e:
        with contextlib.suppress(OSError):
            _retry(rename, old, exe)
        raise UpdateError(f"無法放入新版程式檔: {e}") from e
    with contextlib.suppress(OSError):
        version_marker(exe).unlink()


def restart_command(exe: Path, argv: list[str]) -> list[str]:
    return [str(exe), *argv[1:]]


def restart_env(base) -> dict:
    env = dict(base)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # 新程序重新解壓，不沿用父程序的 _MEI 暫存
    return env


def cleanup_after_update(exe: Path) -> None:
    with contextlib.suppress(OSError):
        old_path(Path(exe)).unlink()
