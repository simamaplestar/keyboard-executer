"""logging → Qt signal 橋（app 薄件）：record→字串 payload、等級過濾、掛載/拆除。"""
import logging

from keyboard_executor.app.qt_log_handler import (
    QtLogHandler,
    attach_gui_handler,
    detach_gui_handler,
)


def make_record(level, message):
    return logging.LogRecord(name="keyboard_executor.core.player", level=level,
                             pathname=__file__, lineno=1, msg=message,
                             args=(), exc_info=None)


def test_handler_formats_record_and_emits_line(qapp):
    lines = []
    handler = QtLogHandler()
    handler.bridge.line.connect(lines.append)
    handler.emit(make_record(logging.WARNING, "規則失敗：甲"))
    assert len(lines) == 1
    assert "[WARNING] 規則失敗：甲" in lines[0]   # HH:MM:SS 前綴由 formatter 提供


def test_handler_level_filters_records(qapp):
    lines = []
    handler = QtLogHandler()
    handler.setLevel(logging.ERROR)
    handler.bridge.line.connect(lines.append)
    handler.handle(make_record(logging.WARNING, "低於等級"))
    handler.handle(make_record(logging.ERROR, "達到等級"))
    assert len(lines) == 1 and "達到等級" in lines[0]


def test_attach_and_detach_gui_handler(qapp):
    lines = []
    handler = attach_gui_handler(lines.append, level="WARNING")
    try:
        logging.getLogger("keyboard_executor.app.somewhere").warning("橋接訊息")
        assert any("橋接訊息" in line for line in lines)
    finally:
        detach_gui_handler(handler)
    logging.getLogger("keyboard_executor.app.somewhere").warning("拆除後")
    assert not any("拆除後" in line for line in lines)
