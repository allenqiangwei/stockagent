import pytest
import os
import tempfile
import yaml
from src.utils.config import Config, ConfigError


class TestConfig:
    def test_load_valid_config(self, tmp_path):
        """测试加载有效配置文件"""
        config_content = {
            "tushare": {"token": "test_token"},
            "storage": {"parquet_dir": "data/market_data"},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_content))

        config = Config(str(config_file))

        assert config.get("tushare.token") == "test_token"
        assert config.get("storage.parquet_dir") == "data/market_data"

    def test_get_nested_key(self, tmp_path):
        """测试获取嵌套配置"""
        config_content = {
            "collector": {
                "primary_source": "tushare",
                "fallback_sources": ["akshare", "baostock"],
            }
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_content))

        config = Config(str(config_file))

        assert config.get("collector.primary_source") == "tushare"
        assert config.get("collector.fallback_sources") == ["akshare", "baostock"]

    def test_get_with_default(self, tmp_path):
        """测试获取不存在的key返回默认值"""
        config_content = {"tushare": {"token": "test"}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_content))

        config = Config(str(config_file))

        assert config.get("nonexistent.key", "default") == "default"
        assert config.get("nonexistent.key") is None

    def test_missing_file_raises_error(self):
        """测试文件不存在抛出异常"""
        with pytest.raises(ConfigError):
            Config("/nonexistent/path/config.yaml")

    def test_invalid_yaml_raises_error(self, tmp_path):
        """测试无效YAML格式抛出异常"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: content: [")

        with pytest.raises(ConfigError):
            Config(str(config_file))
