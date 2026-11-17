"""全套件共用基座：每測後重置套件根 logger 的 handlers。

setup_logging / attach_gui_handler 掛在全域 logging 狀態上（跨測試存活），
不清理會讓 handler 累積：後續測試把記錄寫進已刪除 tmp 目錄的檔案、或投遞給
已銷毀的 widget。autouse 每測後拆除，測試彼此隔離。本檔不得 import PySide6
（非 GUI 測試不碰 Qt）。"""
import logging

import pytest


@pytest.fixture(autouse=True)
def _reset_package_logger():
    yield
    logger = logging.getLogger("keyboard_executor")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
