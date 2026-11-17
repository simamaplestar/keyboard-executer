"""下載新版 EXE 到原 EXE 旁邊並驗證（大小＋SHA-256），以鎖檔避免多開同時下載。

檔案配置（皆在 EXE 同資料夾）：
  <exe>.download     下載中（失敗即刪）
  <exe>.new          已驗證的新版
  <exe>.new.version  .new 的版本號（有它 .new 才算完整）
  <exe>.update.lock  下載鎖"""
from __future__ import annotations

import contextlib
import hashlib
import os
import time
import urllib.request
from pathlib import Path

from keyboard_executor.core.update.release import (
    ReleaseInfo, UpdateError, parse_sha256, user_agent,
)

LOCK_STALE_SEC = 3600
READ_TIMEOUT_SEC = 60.0


class FolderNotWritable(UpdateError):
    """EXE 所在資料夾不能寫入（例如 Program Files），無法自動更新。"""


class UpdateInProgress(UpdateError):
    """另一個程式正在下載同一份更新。"""


def _sibling(exe: Path, suffix: str) -> Path:
    return exe.with_name(exe.name + suffix)


def staged_path(exe: Path) -> Path:
    return _sibling(exe, ".new")


def version_marker(exe: Path) -> Path:
    return _sibling(exe, ".new.version")


def _download_path(exe: Path) -> Path:
    return _sibling(exe, ".download")


def _lock_path(exe: Path) -> Path:
    return _sibling(exe, ".update.lock")


def staged_version(exe: Path) -> str | None:
    marker = version_marker(exe)
    if not staged_path(exe).is_file() or not marker.is_file():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


class UpdateLock:
    def __init__(self):
        self._path: Path | None = None

    def acquire(self, exe: Path, *, now=time.time) -> bool:
        path = _lock_path(exe)
        for _ in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    stale = now() - os.path.getmtime(path) > LOCK_STALE_SEC
                except OSError:
                    stale = True        # 鎖剛被釋放：再搶一次
                if not stale:
                    return False
                with contextlib.suppress(OSError):
                    os.unlink(path)
                continue
            except PermissionError as e:
                if path.exists():
                    return False        # Windows：鎖檔刪除中也回 PermissionError，視為被占用
                raise FolderNotWritable(f"程式所在資料夾無法寫入: {exe.parent}") from e
            os.close(fd)
            self._path = path
            return True
        return False

    def release(self) -> None:
        if self._path is not None:
            with contextlib.suppress(OSError):
                os.unlink(self._path)
            self._path = None


def replace_with_retry(src: Path, dst: Path, *, attempts: int = 5, delay: float = 0.2) -> None:
    """os.replace，遇到暫時性鎖定（防毒掃描剛寫好的檔案）重試幾次。"""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _remove(*paths: Path) -> None:
    for path in paths:
        with contextlib.suppress(OSError):
            path.unlink()


def _open(opener, url: str, current: str):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent(current)})
    return opener(request, timeout=READ_TIMEOUT_SEC)


def download_release(info: ReleaseInfo, exe: Path, *, opener=None, chunk: int = 1 << 20,
                     on_progress=None, current: str = "0.0.0") -> Path:
    """回傳已驗證的 <exe>.new。已有同版就直接回；失敗拋 UpdateError 且不留殘檔。"""
    exe = Path(exe)
    opener = opener or urllib.request.urlopen
    if staged_version(exe) == info.version:
        return staged_path(exe)
    lock = UpdateLock()
    if not lock.acquire(exe):
        raise UpdateInProgress("另一個程式正在下載更新")
    try:
        if staged_version(exe) == info.version:     # 等鎖期間別的程式已下載完成
            return staged_path(exe)
        _remove(staged_path(exe), version_marker(exe))
        temp = _download_path(exe)
        try:
            with _open(opener, info.sha_url, current) as response:
                expected_sha = parse_sha256(response.read(4096).decode("utf-8", "replace"))
            digest = hashlib.sha256()
            done = 0
            with _open(opener, info.exe_url, current) as response, open(temp, "wb") as out:
                while True:
                    block = response.read(chunk)
                    if not block:
                        break
                    out.write(block)
                    digest.update(block)
                    done += len(block)
                    if on_progress is not None:
                        on_progress(done, info.exe_size)
            if done != info.exe_size:
                raise UpdateError(f"下載的檔案大小不符（{done} / {info.exe_size} bytes）")
            if digest.hexdigest() != expected_sha:
                raise UpdateError("下載的檔案 SHA-256 不符，已丟棄")
            replace_with_retry(temp, staged_path(exe))
            version_marker(exe).write_text(info.version, encoding="utf-8")
        except UpdateError:
            _remove(temp, staged_path(exe), version_marker(exe))
            raise
        except (OSError, ValueError) as e:
            _remove(temp, staged_path(exe), version_marker(exe))
            raise UpdateError(f"下載新版失敗: {e}") from e
        return staged_path(exe)
    finally:
        lock.release()
