import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from keyboard_executor.app.update_controller import (
    BUSY_RETRY_SEC, CHECK_INTERVAL_SEC, REMIND_AFTER_SEC, START_DELAY_SEC, UpdateController,
)
from keyboard_executor.core.update.download import FolderNotWritable, UpdateInProgress
from keyboard_executor.core.update.release import RELEASES_PAGE, ReleaseInfo, UpdateError

NEW = ReleaseInfo("0.6.0", "修正", "https://x/exe", 10, "https://x/sha")


def sync(fn, on_done):
    on_done(fn())


class Harness:
    def __init__(self, *, release=NEW, auto=True, busy=False, exe=Path("C:/KE.exe"),
                 download_error=None):
        self.release = release
        self.auto = auto
        self.busy = busy
        self.fetches = 0
        self.downloads = 0
        self.download_error = download_error
        self.ready, self.manual, self.finished = [], [], []
        self.ctrl = UpdateController(
            exe=exe, current="0.5.0",
            get_settings=lambda: SimpleNamespace(auto_update=self.auto),
            is_busy=lambda: self.busy, fetch=self.fetch, download=self.download,
            run_in_background=sync)
        self.ctrl.update_ready.connect(self.ready.append)
        self.ctrl.manual_update_needed.connect(self.manual.append)
        self.ctrl.check_finished.connect(self.finished.append)

    def fetch(self, *, current):
        self.fetches += 1
        if isinstance(self.release, Exception):
            raise self.release
        return self.release

    def download(self, info, exe, *, current):
        self.downloads += 1
        if self.download_error is not None:
            raise self.download_error
        return Path(str(exe) + ".new")


def test_constants():
    assert (START_DELAY_SEC, CHECK_INTERVAL_SEC, REMIND_AFTER_SEC, BUSY_RETRY_SEC) == (
        5, 6 * 3600, 30 * 60, 10)


def test_disabled_without_exe(qapp):
    h = Harness(exe=None)
    assert h.ctrl.enabled is False
    h.ctrl.start()
    assert not h.ctrl._check_timer.isActive()
    h.ctrl.check_now()
    assert h.finished == ["從原始碼執行，不檢查更新"] and h.fetches == 0


def test_start_schedules_first_check(qapp):
    h = Harness()
    h.ctrl.start()
    assert h.ctrl._check_timer.isActive()
    assert h.ctrl._check_timer.interval() == START_DELAY_SEC * 1000
    h.ctrl._on_check_timer()
    assert h.ctrl._check_timer.interval() == CHECK_INTERVAL_SEC * 1000
    h.ctrl.shutdown()


def test_newer_release_downloads_and_signals(qapp):
    h = Harness()
    h.ctrl._on_check_timer()
    assert h.ready == [NEW]
    assert h.downloads == 1
    assert "0.6.0" in h.finished[-1]


def test_same_version_reports_up_to_date(qapp):
    h = Harness(release=ReleaseInfo("0.5.0", "", "https://x/e", 1, "https://x/s"))
    h.ctrl.check_now()
    assert h.finished == ["已是最新版本 0.5.0"]
    assert h.downloads == 0 and h.ready == []


def test_network_error_is_silent(qapp, caplog):
    h = Harness(release=UpdateError("offline"))
    with caplog.at_level(logging.WARNING):
        h.ctrl._on_check_timer()
    assert h.ready == [] and h.manual == []
    assert "檢查失敗" in h.finished[-1]
    assert any("offline" in r.getMessage() for r in caplog.records)


def test_busy_defers_until_idle(qapp):
    h = Harness(busy=True)
    h.ctrl._on_check_timer()
    assert h.ready == []
    assert h.ctrl._remind_timer.isActive()
    assert h.ctrl._remind_timer.interval() == BUSY_RETRY_SEC * 1000
    h.busy = False
    h.ctrl._on_remind_timer()
    assert h.ready == [NEW]


def test_postpone_waits(qapp):
    h = Harness()
    h.ctrl._on_check_timer()
    h.ctrl.postpone()
    assert h.ctrl._remind_timer.interval() == REMIND_AFTER_SEC * 1000
    h.ctrl._on_check_timer()             # 6 小時排程又檢查到同一版
    assert h.ready == [NEW]              # 不重發
    h.ctrl._on_remind_timer()
    assert h.ready == [NEW, NEW]
    h.ctrl.shutdown()


def test_manual_check_overrides_postpone(qapp):
    h = Harness()
    h.ctrl._on_check_timer()
    h.ctrl.postpone()
    h.ctrl.check_now()
    assert h.ready == [NEW, NEW]
    h.ctrl.shutdown()


def test_auto_update_off_skips_timer_check(qapp):
    h = Harness(auto=False)
    h.ctrl._on_check_timer()
    assert h.fetches == 0
    h.ctrl.check_now()
    assert h.fetches == 1


def test_unwritable_folder_signals_manual_once(qapp):
    h = Harness(download_error=FolderNotWritable("denied"))
    h.ctrl._on_check_timer()
    h.ctrl._on_check_timer()
    assert h.manual == [RELEASES_PAGE]
    assert h.ready == []
    assert "手動" in h.finished[-1]


def test_other_instance_downloading_is_quiet(qapp):
    h = Harness(download_error=UpdateInProgress("busy"))
    h.ctrl._on_check_timer()
    assert h.ready == [] and h.manual == []
    assert "另一個" in h.finished[-1]


def test_second_check_while_running_is_ignored(qapp):
    pending = []
    h = Harness()
    h.ctrl._run_in_background = lambda fn, on_done: pending.append((fn, on_done))
    h.ctrl.check_now()
    h.ctrl.check_now()
    assert len(pending) == 1
    fn, on_done = pending[0]
    on_done(fn())
    assert h.fetches == 1 and h.ready == [NEW]


def test_default_background_runner_delivers_on_gui_thread(qapp):
    import time

    from PySide6.QtCore import QCoreApplication
    ctrl = UpdateController(exe=Path("C:/KE.exe"), current="0.5.0",
                            get_settings=lambda: SimpleNamespace(auto_update=True),
                            is_busy=lambda: False, fetch=lambda current: NEW,
                            download=lambda info, exe, current: Path("x"))
    got = []
    ctrl.update_ready.connect(got.append)
    ctrl.check_now()
    deadline = time.monotonic() + 5
    while not got and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert got == [NEW]


def test_install_failed_twice_gives_up_on_version(qapp):
    h = Harness()
    h.ctrl._on_check_timer()
    assert h.ready == [NEW]
    h.ctrl.install_failed("0.6.0")
    h.ctrl._on_remind_timer()
    assert h.ready == [NEW, NEW]               # 第一次失敗：稍後再提醒
    h.ctrl.install_failed("0.6.0")
    h.ctrl._on_remind_timer()
    h.ctrl._on_check_timer()
    assert h.ready == [NEW, NEW]               # 第二次失敗：這版不再提示
    assert h.downloads == 1                    # 也不再重下載
    assert "手動" in h.finished[-1]
    h.ctrl.shutdown()


def test_exe_replaced_by_other_instance_skips_download(qapp, tmp_path):
    exe = tmp_path / "KE.exe"
    exe.write_bytes(b"old")
    h = Harness(exe=exe)
    assert h.ctrl.exe_replaced() is False
    exe.write_bytes(b"new-version-bytes")      # 另一個程式已換上新版
    assert h.ctrl.exe_replaced() is True
    h.ctrl._on_check_timer()
    assert h.downloads == 0
    assert h.ready == [NEW]


def test_old_exe_cleanup_scheduled_after_start(qapp, tmp_path):
    from keyboard_executor.app.update_controller import OLD_CLEANUP_DELAY_SEC
    exe = tmp_path / "KE.exe"
    exe.write_bytes(b"x")
    (tmp_path / "KE.exe.old").write_bytes(b"old")
    h = Harness(exe=exe)
    h.ctrl.start()
    assert h.ctrl._cleanup_timer.isActive()
    assert h.ctrl._cleanup_timer.interval() == OLD_CLEANUP_DELAY_SEC * 1000
    assert (tmp_path / "KE.exe.old").exists()  # 新版要先正常跑一段時間才刪
    h.ctrl._on_cleanup_timer()
    assert not (tmp_path / "KE.exe.old").exists()
    h.ctrl.shutdown()


def test_ready_and_busy_are_logged(qapp, caplog):
    h = Harness(busy=True)
    with caplog.at_level(logging.INFO):
        h.ctrl._on_check_timer()
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "新版 0.6.0 已下載" in text
    assert "忙碌" in text
    h.ctrl.shutdown()
