import pytest
import os
from src.utils.logger import setup_logger, get_logger


class TestLogger:
    def test_setup_logger_creates_file(self, tmp_path):
        """测试日志文件创建"""
        log_file = tmp_path / "test.log"
        setup_logger(str(log_file), level="DEBUG")

        logger = get_logger("test")
        logger.info("test message")

        assert log_file.exists()
        content = log_file.read_text()
        assert "test message" in content

    def test_get_logger_returns_named_logger(self):
        """测试获取命名logger"""
        logger = get_logger("my_module")
        assert logger is not None

    def test_logger_levels(self, tmp_path):
        """测试日志级别过滤"""
        log_file = tmp_path / "level_test.log"
        setup_logger(str(log_file), level="WARNING")

        logger = get_logger("level_test")
        logger.debug("debug msg")
        logger.info("info msg")
        logger.warning("warning msg")
        logger.error("error msg")

        content = log_file.read_text()
        assert "debug msg" not in content
        assert "info msg" not in content
        assert "warning msg" in content
        assert "error msg" in content
