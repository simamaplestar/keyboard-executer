"""自動更新排程：定時查詢公開倉庫最新版、背景下載驗證、閒置時通知主視窗。

網路與下載在背景執行緒，結果經 Qt 訊號回到 GUI 執行緒。失敗只寫 log＋設定頁
結果文字，不跳視窗（spec：不打擾朋友）。忙碌時（腳本／監看／試跑／對話框）
不發 update_ready，每 BUSY_RETRY_SEC 重看一次。"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from keyboard_executor.core.update.install import cleanup_after_update
from keyboard_executor.core.update.download import (
    FolderNotWritable, UpdateInProgress, download_release,
)
from keyboard_executor.core.update.release import (
    RELEASES_PAGE, UpdateError, fetch_latest, is_newer,
)

logger = logging.getLogger(__name__)

START_DELAY_SEC = 5
CHECK_INTERVAL_SEC = 6 * 3600
REMIND_AFTER_SEC = 30 * 60
BUSY_RETRY_SEC = 10            # 忙碌時多久再看一次（關掉對話框後很快就提示）
OLD_CLEANUP_DELAY_SEC = 600     # 新版正常跑 10 分鐘才刪 <exe>.old（壞版本時還能手動改回）
MAX_INSTALL_FAILURES = 2


def _file_stamp(path: Path | None):
    try:
        st = path.stat()
        return (st.st_size, st.st_mtime_ns)
    except (OSError, AttributeError):
        return None


class UpdateController(QObject):
    update_ready = Signal(object)          # ReleaseInfo：已下載驗證，且此刻不忙
    manual_update_needed = Signal(str)     # 下載頁網址：資料夾不可寫，每版一次
    check_finished = Signal(str)           # 給設定頁的繁中結果文字
    _bg_done = Signal(object, object)      # (on_done, result)：背景執行緒 → GUI 執行緒

    def __init__(self, *, exe: Path | None, current: str, get_settings, is_busy,
                 fetch=fetch_latest, download=download_release, run_in_background=None,
                 parent=None):
        super().__init__(parent)
        self._exe = Path(exe) if exe is not None else None
        self._current = current
        self._get_settings = get_settings
        self._is_busy = is_busy
        self._fetch = fetch
        self._download = download
        self._run_in_background = run_in_background or self._thread_runner
        self._bg_done.connect(lambda on_done, result: on_done(result))
        self._running = False
        self._ready = None
        self._postponed = False
        self._manual_notified: set[str] = set()
        self._install_failures: dict[str, int] = {}
        self._given_up: set[str] = set()
        self._exe_stamp = _file_stamp(self._exe)
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.setSingleShot(True)
        self._cleanup_timer.timeout.connect(self._on_cleanup_timer)
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._on_check_timer)
        self._remind_timer = QTimer(self)
        self._remind_timer.setSingleShot(True)
        self._remind_timer.timeout.connect(self._on_remind_timer)

    @property
    def exe(self) -> Path | None:
        return self._exe

    @property
    def enabled(self) -> bool:
        return self._exe is not None

    def start(self) -> None:
        if not self.enabled:
            return
        self._check_timer.start(START_DELAY_SEC * 1000)
        self._cleanup_timer.start(OLD_CLEANUP_DELAY_SEC * 1000)

    def shutdown(self) -> None:
        self._check_timer.stop()
        self._remind_timer.stop()
        self._cleanup_timer.stop()

    def exe_replaced(self) -> bool:
        """另一個開著的程式已經把 EXE 換成新版（檔案大小/時間和啟動時不同）。"""
        return self._exe_stamp is not None and _file_stamp(self._exe) != self._exe_stamp

    def install_failed(self, version: str) -> None:
        count = self._install_failures.get(version, 0) + 1
        self._install_failures[version] = count
        if count < MAX_INSTALL_FAILURES:
            self.postpone()
            return
        self._given_up.add(version)
        self._ready = None
        logger.warning("新版 %s 安裝失敗 %d 次，不再自動提示", version, count)
        self.check_finished.emit(f"新版 {version} 自動更新失敗，請到下載頁手動更新")

    def check_now(self) -> None:
        if not self.enabled:
            self.check_finished.emit("從原始碼執行，不檢查更新")
            return
        self._check(manual=True)

    def postpone(self) -> None:
        self._postponed = True
        self._remind_timer.start(REMIND_AFTER_SEC * 1000)

    # ---- 計時器 ----
    def _on_check_timer(self) -> None:
        if self._check_timer.interval() != CHECK_INTERVAL_SEC * 1000:
            self._check_timer.setInterval(CHECK_INTERVAL_SEC * 1000)
        if not self.enabled or not self._get_settings().auto_update:
            return
        self._check(manual=False)

    def _on_cleanup_timer(self) -> None:
        if self._exe is not None:
            cleanup_after_update(self._exe)

    def _on_remind_timer(self) -> None:
        self._postponed = False
        self._offer()

    # ---- 檢查與下載 ----
    def _check(self, *, manual: bool) -> None:
        if self._running:
            return
        self._running = True
        self._run_in_background(self._job, lambda result: self._on_done(result, manual))

    def _job(self):
        info = None
        try:
            info = self._fetch(current=self._current)
            if not is_newer(info.version, self._current):
                return ("latest", info)
            if info.version in self._given_up:
                return ("given_up", info)
            if self.exe_replaced():
                return ("ready", info)      # 另一個程式已換好新版：重新啟動即可
            self._download(info, self._exe, current=self._current)
            return ("ready", info)
        except FolderNotWritable as e:
            if info is None:
                return ("error", None, e)
            return ("manual", info, e)
        except UpdateInProgress as e:
            return ("in_progress", None, e)
        except (UpdateError, ValueError) as e:
            return ("error", None, e)
        except Exception as e:             # 背景執行緒：任何意外都不可讓程式崩潰
            logger.exception("檢查更新發生未預期錯誤")
            return ("error", None, e)

    def _on_done(self, result, manual: bool) -> None:
        self._running = False
        kind, info = result[0], result[1]
        if kind == "latest":
            self.check_finished.emit(f"已是最新版本 {self._current}")
        elif kind == "ready":
            logger.info("新版 %s 已下載，等待閒置時提示更新", info.version)
            self._ready = info
            self.check_finished.emit(f"新版 {info.version} 已下載完成")
            if manual:
                self._postponed = False
            self._offer()
        elif kind == "given_up":
            self.check_finished.emit(f"新版 {info.version} 自動更新失敗，請到下載頁手動更新")
        elif kind == "manual":
            logger.info("程式所在資料夾無法寫入，無法自動更新：%s", result[2])
            self.check_finished.emit(f"新版 {info.version} 無法自動更新（資料夾無法寫入），請到下載頁手動更新")
            if info.version not in self._manual_notified:
                self._manual_notified.add(info.version)
                self.manual_update_needed.emit(RELEASES_PAGE)
        elif kind == "in_progress":
            logger.info("另一個開著的程式正在下載更新")
            self.check_finished.emit("另一個開著的程式正在下載更新，稍後再試")
        else:
            logger.warning("檢查更新失敗：%s", result[2])
            self.check_finished.emit(f"檢查失敗：{result[2]}")

    def _offer(self) -> None:
        if self._ready is None or self._postponed:
            return
        if self._is_busy():
            if not self._remind_timer.isActive():
                logger.info("程式忙碌（腳本／監看／試跑／對話框），%d 秒後再提示更新", BUSY_RETRY_SEC)
            self._remind_timer.start(BUSY_RETRY_SEC * 1000)
            return
        self.update_ready.emit(self._ready)

    def _thread_runner(self, fn, on_done) -> None:
        threading.Thread(target=lambda: self._bg_done.emit(on_done, fn()),
                         name="update-check", daemon=True).start()
