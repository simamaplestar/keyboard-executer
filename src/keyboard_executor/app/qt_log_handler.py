"""logging → Qt signal 橋（app 層薄件）：把 LogRecord 格式化後投遞給 GUI 日誌面板。

QtLogHandler 可能在任意執行緒被呼叫（Worker QThread 裡的 Player/RuleEngine
logger 也流到這裡），因此不直接碰 widget，一律經 LogBridge 的 signal——
跨執行緒 emit 由 Qt queued connection 安全投遞到 GUI 執行緒（與 Worker
progress signal 同一治理，M4 既定模式）。"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from keyboard_executor.core.logging_config import PACKAGE_LOGGER

GUI_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
GUI_DATE_FORMAT = "%H:%M:%S"


class LogBridge(QObject):
    line = Signal(str)


class QtLogHandler(logging.Handler):
    """format 後經 bridge.line signal 投遞；emit 例外交給 handleError
    （logging 慣例——日誌本身故障不可拖垮回放/監看）。"""

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self.bridge = LogBridge()
        self.setFormatter(logging.Formatter(GUI_LOG_FORMAT, datefmt=GUI_DATE_FORMAT))

    def handle(self, record: logging.LogRecord) -> bool:
        # 標準 logging 的等級過濾發生在 Logger.callHandlers（呼叫 handle() 前），
        # 直接呼叫 handler.handle()（測試、或未經 logger 派送）不會套用；
        # 這裡補上，讓 setLevel 對直接呼叫 handle() 一樣有效。
        if record.levelno < self.level:
            return False
        return super().handle(record)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.line.emit(self.format(record))
        except Exception:
            self.handleError(record)


def attach_gui_handler(sink, *, level: str = "INFO") -> QtLogHandler:
    """建 QtLogHandler、connect 到 sink（如 MainWindow.append_log）、掛上
    套件根 logger；回傳 handler 供 detach_gui_handler 收尾。"""
    handler = QtLogHandler()
    handler.setLevel(level)
    handler.bridge.line.connect(sink)
    logging.getLogger(PACKAGE_LOGGER).addHandler(handler)
    return handler


def detach_gui_handler(handler: QtLogHandler | None) -> None:
    """自套件根 logger 拆除 GUI 橋（關窗收尾；None 安全 no-op）。"""
    if handler is None:
        return
    logging.getLogger(PACKAGE_LOGGER).removeHandler(handler)
    handler.close()
