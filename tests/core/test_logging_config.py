"""集中式日誌設定（M4 待辦 #2：stderr 打包後不可見 → logging 收斂，spec §10）。"""
import logging
from logging.handlers import RotatingFileHandler

from keyboard_executor.core.logging_config import PACKAGE_LOGGER, setup_logging


def test_setup_logging_writes_rotating_file(tmp_path):
    logger = setup_logging(tmp_path / "logs")
    logger.warning("測試訊息：%s", "甲")
    log_file = tmp_path / "logs" / "app.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "測試訊息：甲" in content
    assert "[WARNING]" in content
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 1_000_000
    assert file_handlers[0].backupCount == 3


def test_setup_logging_idempotent(tmp_path):
    setup_logging(tmp_path / "logs")
    logger = setup_logging(tmp_path / "logs")   # 重複呼叫不得累積 handler
    assert len(logger.handlers) == 2            # RotatingFileHandler + StreamHandler
    logger.warning("只出現一次")
    content = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert content.count("只出現一次") == 1


def test_setup_logging_respects_level(tmp_path):
    logger = setup_logging(tmp_path / "logs", level="WARNING")
    logger.info("不該寫入")
    logger.warning("該寫入")
    content = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "不該寫入" not in content
    assert "該寫入" in content


def test_module_loggers_propagate_into_package_log(tmp_path):
    """各模組 logging.getLogger(__name__) 屬 keyboard_executor.* 階層，
    記錄必須流進 setup_logging 掛的檔案 handler（階層契約）。"""
    setup_logging(tmp_path / "logs")
    logging.getLogger(f"{PACKAGE_LOGGER}.core.player").warning("子模組訊息")
    content = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "子模組訊息" in content
    assert "keyboard_executor.core.player" in content
