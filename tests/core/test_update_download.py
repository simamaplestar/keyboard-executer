import hashlib
import io
import os

import pytest

from keyboard_executor.core.update import download as dl
from keyboard_executor.core.update.download import (
    LOCK_STALE_SEC, FolderNotWritable, UpdateLock, download_release, staged_path,
    staged_version, version_marker,
)
from keyboard_executor.core.update.release import ReleaseInfo, UpdateError

PAYLOAD = b"new-exe-bytes" * 1000


def info(size=len(PAYLOAD), version="0.6.0"):
    return ReleaseInfo(version, "notes", "https://x/exe", size, "https://x/sha")


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def make_opener(payload=PAYLOAD, sha=None, calls=None):
    sha = sha if sha is not None else hashlib.sha256(payload).hexdigest()

    def opener(request, timeout):
        url = request.full_url
        if calls is not None:
            calls.append(url)
        if url == "https://x/sha":
            return Resp(f"{sha}  KeyboardExecutor.exe\n".encode())
        return Resp(payload)
    return opener


@pytest.fixture
def exe(tmp_path):
    path = tmp_path / "KeyboardExecutor.exe"
    path.write_bytes(b"old")
    return path


def leftovers(exe):
    return sorted(p.name for p in exe.parent.iterdir() if p != exe)


def test_paths(exe):
    assert staged_path(exe).name == "KeyboardExecutor.exe.new"
    assert version_marker(exe).name == "KeyboardExecutor.exe.new.version"


def test_download_verifies_and_stages(exe):
    out = download_release(info(), exe, opener=make_opener(), chunk=1000)
    assert out == staged_path(exe)
    assert out.read_bytes() == PAYLOAD
    assert staged_version(exe) == "0.6.0"
    assert exe.read_bytes() == b"old"
    assert not (exe.parent / "KeyboardExecutor.exe.download").exists()


def test_progress_reported(exe):
    seen = []
    download_release(info(), exe, opener=make_opener(), chunk=4000,
                     on_progress=lambda done, total: seen.append((done, total)))
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))


def test_size_mismatch_cleans_up(exe):
    with pytest.raises(UpdateError, match="大小"):
        download_release(info(), exe, opener=make_opener(payload=PAYLOAD[:-1]))
    assert leftovers(exe) == []
    assert exe.read_bytes() == b"old"


def test_sha_mismatch_cleans_up(exe):
    with pytest.raises(UpdateError, match="SHA"):
        download_release(info(), exe, opener=make_opener(sha="0" * 64))
    assert leftovers(exe) == []


class DropResp(Resp):
    def __init__(self):
        super().__init__(PAYLOAD)
        self.reads = 0

    def read(self, n=-1):
        self.reads += 1
        if self.reads == 2:
            raise OSError("connection reset")
        return super().read(n)


def test_connection_drop_mid_stream(exe):
    base = make_opener()

    def opener(request, timeout):
        return DropResp() if request.full_url == "https://x/exe" else base(request, timeout)
    with pytest.raises(UpdateError, match="connection reset"):
        download_release(info(), exe, opener=opener, chunk=1000)
    assert leftovers(exe) == []


def test_existing_staged_same_version_skips_network(exe):
    download_release(info(), exe, opener=make_opener())

    def opener(request, timeout):
        raise AssertionError("不應再連網")
    assert download_release(info(), exe, opener=opener) == staged_path(exe)


def test_older_staged_version_is_replaced(exe):
    download_release(info(version="0.5.5"), exe, opener=make_opener())
    calls = []
    download_release(info(version="0.6.0"), exe, opener=make_opener(calls=calls))
    assert calls and staged_version(exe) == "0.6.0"


def test_staged_without_marker_is_ignored(exe):
    staged_path(exe).write_bytes(b"half")
    assert staged_version(exe) is None


def test_lock_excludes_second_holder(exe):
    first, second = UpdateLock(), UpdateLock()
    assert first.acquire(exe) is True
    assert second.acquire(exe) is False
    first.release()
    assert second.acquire(exe) is True
    second.release()
    assert leftovers(exe) == []


def test_stale_lock_is_taken_over(exe):
    first = UpdateLock()
    assert first.acquire(exe)
    mtime = os.path.getmtime(exe.parent / "KeyboardExecutor.exe.update.lock")
    assert UpdateLock().acquire(exe, now=lambda: mtime + LOCK_STALE_SEC + 1) is True


def test_unwritable_folder_raises(exe, monkeypatch):
    def deny(*a, **k):
        raise PermissionError("denied")
    monkeypatch.setattr(dl.os, "open", deny)
    with pytest.raises(FolderNotWritable):
        UpdateLock().acquire(exe)
    assert issubclass(FolderNotWritable, UpdateError)


def test_download_while_other_holds_lock_raises_in_progress(exe):
    from keyboard_executor.core.update.download import UpdateInProgress
    other = UpdateLock()
    assert other.acquire(exe)
    with pytest.raises(UpdateInProgress):
        download_release(info(), exe, opener=make_opener())
    other.release()


def test_permission_error_while_lock_exists_means_held_not_unwritable(exe, monkeypatch):
    # Windows：鎖檔「刪除中」時 O_EXCL 會回 PermissionError，不是資料夾不可寫
    (exe.parent / "KeyboardExecutor.exe.update.lock").write_text("")

    def deny(*a, **k):
        raise PermissionError("delete pending")
    monkeypatch.setattr(dl.os, "open", deny)
    monkeypatch.setattr(dl.os.path, "getmtime", lambda p: 10**12)
    assert UpdateLock().acquire(exe, now=lambda: 10**12) is False


def test_replace_retried_when_scanner_holds_file(exe, monkeypatch):
    real = os.replace
    attempts = {"n": 0}

    def flaky_replace(src, dst):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise PermissionError("sharing violation")
        return real(src, dst)
    monkeypatch.setattr(dl.os, "replace", flaky_replace)
    monkeypatch.setattr(dl.time, "sleep", lambda s: None)
    assert download_release(info(), exe, opener=make_opener()) == staged_path(exe)
    assert attempts["n"] == 3


def test_replace_still_locked_is_not_folder_unwritable(exe, monkeypatch):
    def locked(src, dst):
        raise PermissionError("sharing violation")
    monkeypatch.setattr(dl.os, "replace", locked)
    monkeypatch.setattr(dl.time, "sleep", lambda s: None)
    with pytest.raises(UpdateError) as err:
        download_release(info(), exe, opener=make_opener())
    assert not isinstance(err.value, FolderNotWritable)
    assert leftovers(exe) == []
