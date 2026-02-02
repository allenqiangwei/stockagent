"""配置文件加载和管理模块"""
import os
from typing import Any, Optional
import yaml


class ConfigError(Exception):
    """配置相关错误"""
    pass


class Config:
    """配置管理器

    支持YAML格式配置文件，提供点分隔的嵌套key访问。

    Example:
        config = Config("config/config.yaml")
        token = config.get("tushare.token")
        sources = config.get("collector.fallback_sources", [])
    """

    def __init__(self, config_path: str):
        """初始化配置

        Args:
            config_path: 配置文件路径

        Raises:
            ConfigError: 文件不存在或格式错误
        """
        if not os.path.exists(config_path):
            raise ConfigError(f"配置文件不存在: {config_path}")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"配置文件格式错误: {e}")

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """获取配置值

        支持点分隔的嵌套key，如 "tushare.token"

        Args:
            key: 配置key，支持点分隔
            default: 默认值

        Returns:
            配置值或默认值
        """
        keys = key.split(".")
        value = self._data

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def __getitem__(self, key: str) -> Any:
        """支持字典式访问"""
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value
