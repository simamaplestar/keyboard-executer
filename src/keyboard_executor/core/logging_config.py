"""集中式日誌設定（spec §10：所有事件寫入 GUI 日誌面板與滾動日誌檔）。

純 Python、無 Qt——GUI 端橋接（app/qt_log_handler.py 的 QtLogHandler）只負責
把 LogRecord 轉成 Qt signal。各模組一律 logging.getLogger(__name__) 取
keyboard_executor.* 階層 logger；setup_logging 只掛在套件根 logger 上，
propagate 維持預設 True——記錄照樣流向 root，pytest caplog 免設定即可斷言，
一般執行時 root 無 handler、不會重複輸出。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

PACKAGE_LOGGER = "keyboard_executor"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 1_000_000   # 單檔 1MB
_BACKUP_COUNT = 3        # app.log.1 ~ app.log.3


def setup_logging(log_dir: str | Path, level: str = "INFO") -> logging.Logger:
    """設定套件根 logger：<log_dir>/app.log 滾動檔＋ stderr 串流。

    冪等：重複呼叫（GUI 重啟、測試）會先拆除既有 handlers 再重掛，不會重複
    輸出；GUI 橋（QtLogHandler）由 build_app 在本函式之後另掛。回傳套件根
    logger 供進一步掛載。level 用 settings.json 的 log_level 值
    （DEBUG/INFO/WARNING/ERROR，與 logging 等級名一致）。"""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(PACKAGE_LOGGER)
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    file_handler = RotatingFileHandler(log_dir / "app.log", maxBytes=_MAX_BYTES,
                                       backupCount=_BACKUP_COUNT, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger
