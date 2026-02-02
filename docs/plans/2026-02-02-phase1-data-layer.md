# 第一阶段：数据层实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立可靠的数据采集和存储系统，能够获取全市场3000+只A股的日线数据、指数数据、资金流数据和财经新闻。

**Architecture:** 多源数据采集（TuShare主源 + AkShare/Baostock备用）→ 统一数据格式 → Parquet文件存储历史K线 + SQLite存储业务数据。采用抽象基类设计，便于切换数据源。

**Tech Stack:** Python 3.9+, pandas, pyarrow, tushare, akshare, baostock, requests, beautifulsoup4, sqlite3, pyyaml, loguru, pytest

---

## 前置准备

### Task 0: 项目初始化

**Files:**
- Create: `requirements.txt`
- Create: `config/config.yaml.example`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`

**Step 1: 创建 requirements.txt**

```txt
# Data processing
pandas>=2.0.0
pyarrow>=14.0.0
numpy>=1.24.0

# Data sources
tushare>=1.2.89
akshare>=1.12.0
baostock>=0.8.8

# Web scraping
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=4.9.0

# Database
# sqlite3 is built-in

# Configuration
pyyaml>=6.0.0
python-dotenv>=1.0.0

# Logging
loguru>=0.7.0

# Testing
pytest>=7.4.0
pytest-cov>=4.1.0

# Utilities
schedule>=1.2.0
```

**Step 2: 创建配置文件模板**

`config/config.yaml.example`:
```yaml
# TuShare API Token (从 https://tushare.pro 获取)
tushare:
  token: "your_tushare_token_here"

# 数据存储路径
storage:
  parquet_dir: "data/market_data"
  sqlite_db: "data/business.db"
  backup_dir: "data/backups"

# 数据采集设置
collector:
  # 主数据源: tushare, akshare, baostock
  primary_source: "tushare"
  # 备用数据源列表
  fallback_sources: ["akshare", "baostock"]
  # 每次API请求间隔(秒)，避免频率限制
  request_interval: 0.3
  # 批量请求大小
  batch_size: 100

# 新闻爬虫设置
news:
  # 爬取的新闻数量
  max_articles: 20
  # 请求超时(秒)
  timeout: 10

# 日志设置
logging:
  level: "INFO"
  file: "logs/stockagent.log"
  rotation: "10 MB"
```

**Step 3: 创建目录结构**

```bash
mkdir -p src/data_collector src/data_storage src/utils tests config data/market_data/daily data/market_data/index data/market_data/money_flow logs
touch src/__init__.py src/data_collector/__init__.py src/data_storage/__init__.py src/utils/__init__.py tests/__init__.py
```

**Step 4: 安装依赖**

```bash
pip install -r requirements.txt
```

**Step 5: Commit**

```bash
git add -A
git commit -m "chore: initialize project structure and dependencies"
```

---

## 模块1: 配置和日志工具

### Task 1: 配置加载器

**Files:**
- Create: `src/utils/config.py`
- Create: `tests/test_config.py`

**Step 1: 写失败测试**

`tests/test_config.py`:
```python
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
```

**Step 2: 运行测试验证失败**

```bash
pytest tests/test_config.py -v
```
Expected: FAIL (ModuleNotFoundError: No module named 'src.utils.config')

**Step 3: 实现配置加载器**

`src/utils/config.py`:
```python
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
```

**Step 4: 运行测试验证通过**

```bash
pytest tests/test_config.py -v
```
Expected: PASS (5 passed)

**Step 5: Commit**

```bash
git add src/utils/config.py tests/test_config.py
git commit -m "feat: add config loader with nested key support"
```

---

### Task 2: 日志工具

**Files:**
- Create: `src/utils/logger.py`
- Create: `tests/test_logger.py`

**Step 1: 写失败测试**

`tests/test_logger.py`:
```python
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
```

**Step 2: 运行测试验证失败**

```bash
pytest tests/test_logger.py -v
```
Expected: FAIL

**Step 3: 实现日志工具**

`src/utils/logger.py`:
```python
"""日志配置模块，基于loguru"""
import sys
from loguru import logger


# 移除默认的stderr handler
logger.remove()

_initialized = False


def setup_logger(
    log_file: str = "logs/stockagent.log",
    level: str = "INFO",
    rotation: str = "10 MB",
    retention: str = "30 days",
) -> None:
    """配置日志系统

    Args:
        log_file: 日志文件路径
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        rotation: 日志轮转大小
        retention: 日志保留时间
    """
    global _initialized

    if _initialized:
        logger.remove()

    # 控制台输出
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # 文件输出
    logger.add(
        log_file,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
    )

    _initialized = True


def get_logger(name: str):
    """获取命名logger

    Args:
        name: 模块名称

    Returns:
        绑定了模块名的logger
    """
    return logger.bind(name=name)
```

**Step 4: 运行测试验证通过**

```bash
pytest tests/test_logger.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/utils/logger.py tests/test_logger.py
git commit -m "feat: add logger utility based on loguru"
```

---

## 模块2: 数据存储层

### Task 3: SQLite数据库Schema

**Files:**
- Create: `src/data_storage/database.py`
- Create: `tests/test_database.py`

**Step 1: 写失败测试**

`tests/test_database.py`:
```python
import pytest
import sqlite3
from src.data_storage.database import Database


class TestDatabase:
    def test_create_tables(self, tmp_path):
        """测试创建数据表"""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        db.init_tables()

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        assert "stock_list" in tables
        assert "data_update_log" in tables
        assert "news_sentiment" in tables

        conn.close()

    def test_insert_and_query_stock_list(self, tmp_path):
        """测试股票列表的增删改查"""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        db.init_tables()

        # 插入
        stocks = [
            {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行"},
            {"ts_code": "600000.SH", "name": "浦发银行", "industry": "银行"},
        ]
        db.upsert_stock_list(stocks)

        # 查询
        result = db.get_stock_list()
        assert len(result) == 2
        assert result[0]["ts_code"] == "000001.SZ"

    def test_log_data_update(self, tmp_path):
        """测试数据更新日志"""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        db.init_tables()

        db.log_update("daily", "2025-01-15", 3000, "success")

        log = db.get_latest_update("daily")
        assert log["trade_date"] == "2025-01-15"
        assert log["record_count"] == 3000
        assert log["status"] == "success"

    def test_get_latest_update_returns_none_if_empty(self, tmp_path):
        """测试空表返回None"""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        db.init_tables()

        result = db.get_latest_update("daily")
        assert result is None
```

**Step 2: 运行测试验证失败**

```bash
pytest tests/test_database.py -v
```
Expected: FAIL

**Step 3: 实现数据库模块**

`src/data_storage/database.py`:
```python
"""SQLite数据库管理模块"""
import sqlite3
from typing import Optional, List, Dict, Any
from contextlib import contextmanager


class Database:
    """SQLite数据库管理器

    管理股票列表、数据更新日志、新闻情绪等业务数据。
    """

    def __init__(self, db_path: str):
        """初始化数据库连接

        Args:
            db_path: SQLite数据库文件路径
        """
        self.db_path = db_path

    @contextmanager
    def _get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_tables(self) -> None:
        """初始化所有数据表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 股票列表表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_list (
                    ts_code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    industry TEXT,
                    market TEXT,
                    list_date TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 数据更新日志表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS data_update_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_type TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    record_count INTEGER,
                    status TEXT,
                    error_msg TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 新闻情绪表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_sentiment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT,
                    sentiment_score REAL,
                    keywords TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 为常用查询创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_update_log_type_date
                ON data_update_log(data_type, trade_date DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_date
                ON news_sentiment(trade_date DESC)
            """)

    def upsert_stock_list(self, stocks: List[Dict[str, Any]]) -> None:
        """更新或插入股票列表

        Args:
            stocks: 股票信息列表，每个元素包含ts_code, name, industry等
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO stock_list
                (ts_code, name, industry, market, list_date, updated_at)
                VALUES (
                    :ts_code, :name, :industry,
                    :market, :list_date, CURRENT_TIMESTAMP
                )
            """, [
                {
                    "ts_code": s.get("ts_code"),
                    "name": s.get("name"),
                    "industry": s.get("industry"),
                    "market": s.get("market"),
                    "list_date": s.get("list_date"),
                }
                for s in stocks
            ])

    def get_stock_list(self) -> List[Dict[str, Any]]:
        """获取所有股票列表

        Returns:
            股票信息列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stock_list ORDER BY ts_code")
            return [dict(row) for row in cursor.fetchall()]

    def log_update(
        self,
        data_type: str,
        trade_date: str,
        record_count: int,
        status: str,
        error_msg: Optional[str] = None
    ) -> None:
        """记录数据更新日志

        Args:
            data_type: 数据类型 (daily, index, money_flow, news)
            trade_date: 交易日期
            record_count: 记录数量
            status: 状态 (success, failed)
            error_msg: 错误信息
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO data_update_log
                (data_type, trade_date, record_count, status, error_msg)
                VALUES (?, ?, ?, ?, ?)
            """, (data_type, trade_date, record_count, status, error_msg))

    def get_latest_update(self, data_type: str) -> Optional[Dict[str, Any]]:
        """获取指定数据类型的最新更新记录

        Args:
            data_type: 数据类型

        Returns:
            最新更新记录或None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM data_update_log
                WHERE data_type = ?
                ORDER BY trade_date DESC, created_at DESC
                LIMIT 1
            """, (data_type,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_news_sentiment(self, news_list: List[Dict[str, Any]]) -> None:
        """保存新闻情绪数据

        Args:
            news_list: 新闻列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO news_sentiment
                (trade_date, title, source, sentiment_score, keywords)
                VALUES (:trade_date, :title, :source, :sentiment_score, :keywords)
            """, news_list)

    def get_news_by_date(self, trade_date: str) -> List[Dict[str, Any]]:
        """获取指定日期的新闻

        Args:
            trade_date: 交易日期

        Returns:
            新闻列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM news_sentiment
                WHERE trade_date = ?
                ORDER BY created_at DESC
            """, (trade_date,))
            return [dict(row) for row in cursor.fetchall()]
```

**Step 4: 运行测试验证通过**

```bash
pytest tests/test_database.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/data_storage/database.py tests/test_database.py
git commit -m "feat: add SQLite database manager with stock_list and update_log"
```

---

### Task 4: Parquet存储管理器

**Files:**
- Create: `src/data_storage/parquet_storage.py`
- Create: `tests/test_parquet_storage.py`

**Step 1: 写失败测试**

`tests/test_parquet_storage.py`:
```python
import pytest
import pandas as pd
from datetime import date
from src.data_storage.parquet_storage import ParquetStorage


class TestParquetStorage:
    def test_save_and_load_daily_data(self, tmp_path):
        """测试保存和加载日线数据"""
        storage = ParquetStorage(str(tmp_path))

        df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000001.SZ", "600000.SH"],
            "trade_date": ["20250113", "20250114", "20250114"],
            "open": [10.0, 10.5, 8.0],
            "high": [10.5, 11.0, 8.5],
            "low": [9.8, 10.2, 7.9],
            "close": [10.2, 10.8, 8.2],
            "vol": [1000000, 1200000, 800000],
            "amount": [10200000, 12960000, 6560000],
        })

        storage.save_daily("2025", df)

        loaded = storage.load_daily("2025")
        assert len(loaded) == 3
        assert loaded["ts_code"].tolist() == ["000001.SZ", "000001.SZ", "600000.SH"]

    def test_append_daily_data(self, tmp_path):
        """测试追加日线数据"""
        storage = ParquetStorage(str(tmp_path))

        # 先保存一批数据
        df1 = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250113"],
            "open": [10.0], "high": [10.5], "low": [9.8],
            "close": [10.2], "vol": [1000000], "amount": [10200000],
        })
        storage.save_daily("2025", df1)

        # 追加新数据
        df2 = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "open": [10.5], "high": [11.0], "low": [10.2],
            "close": [10.8], "vol": [1200000], "amount": [12960000],
        })
        storage.append_daily("2025", df2)

        loaded = storage.load_daily("2025")
        assert len(loaded) == 2

    def test_load_nonexistent_file_returns_empty(self, tmp_path):
        """测试加载不存在的文件返回空DataFrame"""
        storage = ParquetStorage(str(tmp_path))

        loaded = storage.load_daily("2020")
        assert len(loaded) == 0
        assert isinstance(loaded, pd.DataFrame)

    def test_load_daily_with_date_range(self, tmp_path):
        """测试按日期范围加载数据"""
        storage = ParquetStorage(str(tmp_path))

        df = pd.DataFrame({
            "ts_code": ["000001.SZ"] * 5,
            "trade_date": ["20250110", "20250113", "20250114", "20250115", "20250116"],
            "open": [10.0, 10.5, 10.8, 11.0, 10.5],
            "high": [10.5, 11.0, 11.2, 11.5, 11.0],
            "low": [9.8, 10.2, 10.5, 10.8, 10.2],
            "close": [10.2, 10.8, 11.0, 11.2, 10.6],
            "vol": [1000000] * 5,
            "amount": [10000000] * 5,
        })
        storage.save_daily("2025", df)

        loaded = storage.load_daily("2025", start_date="20250113", end_date="20250115")
        assert len(loaded) == 3
        assert loaded["trade_date"].min() == "20250113"
        assert loaded["trade_date"].max() == "20250115"

    def test_get_latest_trade_date(self, tmp_path):
        """测试获取最新交易日期"""
        storage = ParquetStorage(str(tmp_path))

        df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["20250113", "20250114"],
            "open": [10.0, 10.5], "high": [10.5, 11.0], "low": [9.8, 10.2],
            "close": [10.2, 10.8], "vol": [1000000, 1200000], "amount": [10200000, 12960000],
        })
        storage.save_daily("2025", df)

        latest = storage.get_latest_trade_date("daily")
        assert latest == "20250114"

    def test_save_and_load_index_data(self, tmp_path):
        """测试保存和加载指数数据"""
        storage = ParquetStorage(str(tmp_path))

        df = pd.DataFrame({
            "ts_code": ["000001.SH", "399001.SZ"],
            "trade_date": ["20250114", "20250114"],
            "close": [3200.0, 10500.0],
            "pct_chg": [0.5, 0.8],
        })

        storage.save_index("2025", df)
        loaded = storage.load_index("2025")

        assert len(loaded) == 2
```

**Step 2: 运行测试验证失败**

```bash
pytest tests/test_parquet_storage.py -v
```
Expected: FAIL

**Step 3: 实现Parquet存储管理器**

`src/data_storage/parquet_storage.py`:
```python
"""Parquet文件存储管理模块"""
import os
from typing import Optional
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


class ParquetStorage:
    """Parquet文件存储管理器

    按年份分区存储历史K线数据，支持增量追加和日期范围查询。

    目录结构:
        {base_dir}/
        ├── daily/
        │   ├── 2023.parquet
        │   ├── 2024.parquet
        │   └── 2025.parquet
        ├── index/
        │   └── 2025.parquet
        └── money_flow/
            └── 2025.parquet
    """

    def __init__(self, base_dir: str):
        """初始化存储管理器

        Args:
            base_dir: 数据存储根目录
        """
        self.base_dir = base_dir
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """确保所需目录存在"""
        for subdir in ["daily", "index", "money_flow"]:
            os.makedirs(os.path.join(self.base_dir, subdir), exist_ok=True)

    def _get_file_path(self, data_type: str, year: str) -> str:
        """获取文件路径

        Args:
            data_type: 数据类型 (daily, index, money_flow)
            year: 年份

        Returns:
            完整文件路径
        """
        return os.path.join(self.base_dir, data_type, f"{year}.parquet")

    def _save(self, data_type: str, year: str, df: pd.DataFrame) -> None:
        """保存数据到Parquet文件

        Args:
            data_type: 数据类型
            year: 年份
            df: 数据DataFrame
        """
        file_path = self._get_file_path(data_type, year)
        df.to_parquet(file_path, index=False, compression="snappy")

    def _load(
        self,
        data_type: str,
        year: str,
        columns: Optional[list] = None,
    ) -> pd.DataFrame:
        """加载Parquet文件

        Args:
            data_type: 数据类型
            year: 年份
            columns: 要加载的列（可选）

        Returns:
            数据DataFrame，文件不存在返回空DataFrame
        """
        file_path = self._get_file_path(data_type, year)
        if not os.path.exists(file_path):
            return pd.DataFrame()

        return pd.read_parquet(file_path, columns=columns)

    def _append(self, data_type: str, year: str, df: pd.DataFrame) -> None:
        """追加数据到现有文件

        Args:
            data_type: 数据类型
            year: 年份
            df: 要追加的数据
        """
        existing = self._load(data_type, year)
        if len(existing) > 0:
            combined = pd.concat([existing, df], ignore_index=True)
            # 去重（基于ts_code和trade_date）
            if "ts_code" in combined.columns and "trade_date" in combined.columns:
                combined = combined.drop_duplicates(
                    subset=["ts_code", "trade_date"],
                    keep="last"
                )
        else:
            combined = df

        self._save(data_type, year, combined)

    # ===== Daily Data =====

    def save_daily(self, year: str, df: pd.DataFrame) -> None:
        """保存日线数据

        Args:
            year: 年份
            df: 日线数据
        """
        self._save("daily", year, df)

    def append_daily(self, year: str, df: pd.DataFrame) -> None:
        """追加日线数据

        Args:
            year: 年份
            df: 要追加的日线数据
        """
        self._append("daily", year, df)

    def load_daily(
        self,
        year: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        ts_codes: Optional[list] = None,
    ) -> pd.DataFrame:
        """加载日线数据

        Args:
            year: 年份
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            ts_codes: 股票代码列表

        Returns:
            日线数据DataFrame
        """
        df = self._load("daily", year)
        if len(df) == 0:
            return df

        if start_date:
            df = df[df["trade_date"] >= start_date]
        if end_date:
            df = df[df["trade_date"] <= end_date]
        if ts_codes:
            df = df[df["ts_code"].isin(ts_codes)]

        return df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    # ===== Index Data =====

    def save_index(self, year: str, df: pd.DataFrame) -> None:
        """保存指数数据"""
        self._save("index", year, df)

    def append_index(self, year: str, df: pd.DataFrame) -> None:
        """追加指数数据"""
        self._append("index", year, df)

    def load_index(
        self,
        year: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """加载指数数据"""
        df = self._load("index", year)
        if len(df) == 0:
            return df

        if start_date:
            df = df[df["trade_date"] >= start_date]
        if end_date:
            df = df[df["trade_date"] <= end_date]

        return df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    # ===== Money Flow Data =====

    def save_money_flow(self, year: str, df: pd.DataFrame) -> None:
        """保存资金流数据"""
        self._save("money_flow", year, df)

    def append_money_flow(self, year: str, df: pd.DataFrame) -> None:
        """追加资金流数据"""
        self._append("money_flow", year, df)

    def load_money_flow(
        self,
        year: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """加载资金流数据"""
        df = self._load("money_flow", year)
        if len(df) == 0:
            return df

        if start_date:
            df = df[df["trade_date"] >= start_date]
        if end_date:
            df = df[df["trade_date"] <= end_date]

        return df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    # ===== Utilities =====

    def get_latest_trade_date(self, data_type: str = "daily") -> Optional[str]:
        """获取指定数据类型的最新交易日期

        Args:
            data_type: 数据类型

        Returns:
            最新交易日期 (YYYYMMDD) 或 None
        """
        import datetime
        current_year = datetime.date.today().year

        # 从当前年份向前查找
        for year in range(current_year, current_year - 5, -1):
            df = self._load(data_type, str(year), columns=["trade_date"])
            if len(df) > 0:
                return df["trade_date"].max()

        return None

    def load_daily_multi_year(
        self,
        start_date: str,
        end_date: str,
        ts_codes: Optional[list] = None,
    ) -> pd.DataFrame:
        """加载跨年份的日线数据

        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            ts_codes: 股票代码列表

        Returns:
            合并的日线数据
        """
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])

        dfs = []
        for year in range(start_year, end_year + 1):
            df = self.load_daily(
                str(year),
                start_date=start_date if year == start_year else None,
                end_date=end_date if year == end_year else None,
                ts_codes=ts_codes,
            )
            if len(df) > 0:
                dfs.append(df)

        if not dfs:
            return pd.DataFrame()

        return pd.concat(dfs, ignore_index=True).sort_values(
            ["ts_code", "trade_date"]
        ).reset_index(drop=True)
```

**Step 4: 运行测试验证通过**

```bash
pytest tests/test_parquet_storage.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/data_storage/parquet_storage.py tests/test_parquet_storage.py
git commit -m "feat: add ParquetStorage for daily/index/money_flow data"
```

---

## 模块3: 数据采集层

### Task 5: 数据采集基类

**Files:**
- Create: `src/data_collector/base_collector.py`
- Create: `tests/test_base_collector.py`

**Step 1: 写失败测试**

`tests/test_base_collector.py`:
```python
import pytest
import pandas as pd
from src.data_collector.base_collector import BaseCollector, CollectorError


class MockCollector(BaseCollector):
    """测试用的Mock采集器"""

    def __init__(self):
        super().__init__()
        self._stock_list = pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "name": ["平安银行", "浦发银行"],
        })
        self._daily_data = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "open": [10.0], "high": [10.5], "low": [9.8], "close": [10.2],
            "vol": [1000000], "amount": [10200000],
        })

    def _fetch_stock_list(self) -> pd.DataFrame:
        return self._stock_list

    def _fetch_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._daily_data[self._daily_data["ts_code"] == ts_code]

    def _fetch_index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    def _fetch_money_flow(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame()


class TestBaseCollector:
    def test_get_stock_list(self):
        """测试获取股票列表"""
        collector = MockCollector()
        df = collector.get_stock_list()

        assert len(df) == 2
        assert "ts_code" in df.columns
        assert "name" in df.columns

    def test_get_daily_data(self):
        """测试获取日线数据"""
        collector = MockCollector()
        df = collector.get_daily("000001.SZ", "20250101", "20250114")

        assert len(df) == 1
        assert df.iloc[0]["ts_code"] == "000001.SZ"

    def test_retry_on_failure(self):
        """测试失败重试机制"""
        class FailingCollector(MockCollector):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            def _fetch_stock_list(self) -> pd.DataFrame:
                self.attempts += 1
                if self.attempts < 3:
                    raise Exception("API Error")
                return self._stock_list

        collector = FailingCollector()
        df = collector.get_stock_list()

        assert collector.attempts == 3
        assert len(df) == 2

    def test_max_retries_exceeded_raises_error(self):
        """测试超过最大重试次数抛出异常"""
        class AlwaysFailCollector(MockCollector):
            def _fetch_stock_list(self) -> pd.DataFrame:
                raise Exception("API Error")

        collector = AlwaysFailCollector()
        collector.max_retries = 2

        with pytest.raises(CollectorError):
            collector.get_stock_list()
```

**Step 2: 运行测试验证失败**

```bash
pytest tests/test_base_collector.py -v
```
Expected: FAIL

**Step 3: 实现基类**

`src/data_collector/base_collector.py`:
```python
"""数据采集器基类"""
import time
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


class CollectorError(Exception):
    """数据采集相关错误"""
    pass


class BaseCollector(ABC):
    """数据采集器抽象基类

    定义统一的数据采集接口，所有具体采集器（TuShare、AkShare等）需实现此接口。
    包含自动重试机制。
    """

    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        """初始化采集器

        Args:
            max_retries: 最大重试次数
            retry_delay: 重试间隔(秒)
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _retry(self, func, *args, **kwargs):
        """带重试的函数调用

        Args:
            func: 要执行的函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值

        Raises:
            CollectorError: 超过最大重试次数
        """
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(
                    f"采集失败 (尝试 {attempt}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        raise CollectorError(f"采集失败，已重试{self.max_retries}次: {last_error}")

    # ===== Public Interface =====

    def get_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表

        Returns:
            包含ts_code, name, industry等字段的DataFrame
        """
        return self._retry(self._fetch_stock_list)

    def get_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取单只股票的日线数据

        Args:
            ts_code: 股票代码 (如 000001.SZ)
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)

        Returns:
            日线数据DataFrame
        """
        return self._retry(self._fetch_daily, ts_code, start_date, end_date)

    def get_daily_all(
        self,
        trade_date: str
    ) -> pd.DataFrame:
        """获取指定交易日的所有股票日线数据

        Args:
            trade_date: 交易日期 (YYYYMMDD)

        Returns:
            全市场日线数据
        """
        return self._retry(self._fetch_daily_all, trade_date)

    def get_index_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取指数日线数据

        Args:
            ts_code: 指数代码 (如 000001.SH)
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            指数日线数据
        """
        return self._retry(self._fetch_index_daily, ts_code, start_date, end_date)

    def get_money_flow(self, trade_date: str) -> pd.DataFrame:
        """获取资金流数据

        Args:
            trade_date: 交易日期

        Returns:
            资金流数据
        """
        return self._retry(self._fetch_money_flow, trade_date)

    # ===== Abstract Methods (子类必须实现) =====

    @abstractmethod
    def _fetch_stock_list(self) -> pd.DataFrame:
        """获取股票列表的具体实现"""
        pass

    @abstractmethod
    def _fetch_daily(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取单只股票日线数据的具体实现"""
        pass

    def _fetch_daily_all(self, trade_date: str) -> pd.DataFrame:
        """获取指定日期全市场数据的具体实现

        默认实现为空，因为不是所有数据源都支持此功能
        """
        raise NotImplementedError("此数据源不支持获取全市场日线数据")

    @abstractmethod
    def _fetch_index_daily(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取指数日线数据的具体实现"""
        pass

    @abstractmethod
    def _fetch_money_flow(self, trade_date: str) -> pd.DataFrame:
        """获取资金流数据的具体实现"""
        pass
```

**Step 4: 运行测试验证通过**

```bash
pytest tests/test_base_collector.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/data_collector/base_collector.py tests/test_base_collector.py
git commit -m "feat: add BaseCollector abstract class with retry mechanism"
```

---

### Task 6: TuShare采集器

**Files:**
- Create: `src/data_collector/tushare_collector.py`
- Create: `tests/test_tushare_collector.py`

**Step 1: 写失败测试**

`tests/test_tushare_collector.py`:
```python
import pytest
import pandas as pd
from unittest.mock import Mock, patch
from src.data_collector.tushare_collector import TuShareCollector


class TestTuShareCollector:
    @patch("src.data_collector.tushare_collector.ts")
    def test_fetch_stock_list(self, mock_ts):
        """测试获取股票列表"""
        mock_api = Mock()
        mock_ts.pro_api.return_value = mock_api
        mock_api.stock_basic.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "name": ["平安银行", "浦发银行"],
            "industry": ["银行", "银行"],
            "market": ["主板", "主板"],
            "list_date": ["19910403", "19991110"],
        })

        collector = TuShareCollector("test_token")
        df = collector.get_stock_list()

        assert len(df) == 2
        mock_api.stock_basic.assert_called_once()

    @patch("src.data_collector.tushare_collector.ts")
    def test_fetch_daily(self, mock_ts):
        """测试获取日线数据"""
        mock_api = Mock()
        mock_ts.pro_api.return_value = mock_api
        mock_api.daily.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "vol": [1000000.0],
            "amount": [10200000.0],
        })

        collector = TuShareCollector("test_token")
        df = collector.get_daily("000001.SZ", "20250101", "20250114")

        assert len(df) == 1
        assert df.iloc[0]["close"] == 10.2

    @patch("src.data_collector.tushare_collector.ts")
    def test_fetch_daily_all(self, mock_ts):
        """测试获取全市场日线数据"""
        mock_api = Mock()
        mock_ts.pro_api.return_value = mock_api
        mock_api.daily.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "trade_date": ["20250114", "20250114"],
            "open": [10.0, 8.0],
            "high": [10.5, 8.5],
            "low": [9.8, 7.9],
            "close": [10.2, 8.2],
            "vol": [1000000.0, 800000.0],
            "amount": [10200000.0, 6560000.0],
        })

        collector = TuShareCollector("test_token")
        df = collector.get_daily_all("20250114")

        assert len(df) == 2

    @patch("src.data_collector.tushare_collector.ts")
    def test_fetch_index_daily(self, mock_ts):
        """测试获取指数日线数据"""
        mock_api = Mock()
        mock_ts.pro_api.return_value = mock_api
        mock_api.index_daily.return_value = pd.DataFrame({
            "ts_code": ["000001.SH"],
            "trade_date": ["20250114"],
            "close": [3200.0],
            "pct_chg": [0.5],
        })

        collector = TuShareCollector("test_token")
        df = collector.get_index_daily("000001.SH", "20250101", "20250114")

        assert len(df) == 1
        assert df.iloc[0]["close"] == 3200.0

    @patch("src.data_collector.tushare_collector.ts")
    def test_fetch_money_flow(self, mock_ts):
        """测试获取资金流数据"""
        mock_api = Mock()
        mock_ts.pro_api.return_value = mock_api
        mock_api.moneyflow.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "buy_sm_vol": [100000.0],
            "sell_sm_vol": [80000.0],
            "net_mf_vol": [20000.0],
        })

        collector = TuShareCollector("test_token")
        df = collector.get_money_flow("20250114")

        assert len(df) == 1
```

**Step 2: 运行测试验证失败**

```bash
pytest tests/test_tushare_collector.py -v
```
Expected: FAIL

**Step 3: 实现TuShare采集器**

`src/data_collector/tushare_collector.py`:
```python
"""TuShare数据采集器"""
import time
import pandas as pd
import tushare as ts

from src.data_collector.base_collector import BaseCollector
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TuShareCollector(BaseCollector):
    """TuShare数据采集器

    使用TuShare Pro API获取A股行情数据。
    需要TuShare Pro账号和足够的积分。

    API文档: https://tushare.pro/document/2
    """

    def __init__(
        self,
        token: str,
        request_interval: float = 0.3,
        max_retries: int = 3,
    ):
        """初始化TuShare采集器

        Args:
            token: TuShare Pro API token
            request_interval: 请求间隔(秒)，避免频率限制
            max_retries: 最大重试次数
        """
        super().__init__(max_retries=max_retries)
        self.request_interval = request_interval
        self._api = ts.pro_api(token)

    def _rate_limit(self):
        """请求频率限制"""
        time.sleep(self.request_interval)

    def _fetch_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表

        Returns:
            DataFrame with columns: ts_code, name, industry, market, list_date
        """
        logger.info("正在获取A股股票列表...")
        self._rate_limit()

        df = self._api.stock_basic(
            exchange="",
            list_status="L",  # 上市状态
            fields="ts_code,name,industry,market,list_date"
        )

        logger.info(f"获取到 {len(df)} 只股票")
        return df

    def _fetch_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取单只股票日线数据

        Args:
            ts_code: 股票代码
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)

        Returns:
            日线数据
        """
        self._rate_limit()

        df = self._api.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

        return df

    def _fetch_daily_all(self, trade_date: str) -> pd.DataFrame:
        """获取指定交易日全市场日线数据

        Args:
            trade_date: 交易日期 (YYYYMMDD)

        Returns:
            全市场日线数据
        """
        logger.info(f"正在获取 {trade_date} 全市场日线数据...")
        self._rate_limit()

        df = self._api.daily(trade_date=trade_date)

        logger.info(f"获取到 {len(df)} 条记录")
        return df

    def _fetch_index_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取指数日线数据

        Args:
            ts_code: 指数代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            指数日线数据
        """
        self._rate_limit()

        df = self._api.index_daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

        return df

    def _fetch_money_flow(self, trade_date: str) -> pd.DataFrame:
        """获取资金流数据

        Args:
            trade_date: 交易日期

        Returns:
            资金流数据
        """
        logger.info(f"正在获取 {trade_date} 资金流数据...")
        self._rate_limit()

        df = self._api.moneyflow(trade_date=trade_date)

        logger.info(f"获取到 {len(df)} 条资金流记录")
        return df

    def get_trade_calendar(
        self,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取交易日历

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            交易日历 (is_open=1表示交易日)
        """
        self._rate_limit()

        df = self._api.trade_cal(
            exchange="SSE",
            start_date=start_date,
            end_date=end_date,
        )

        return df

    def get_daily_basic(self, trade_date: str) -> pd.DataFrame:
        """获取每日基本面指标

        包含PE、PB、市值等数据

        Args:
            trade_date: 交易日期

        Returns:
            基本面数据
        """
        logger.info(f"正在获取 {trade_date} 基本面数据...")
        self._rate_limit()

        df = self._api.daily_basic(
            trade_date=trade_date,
            fields="ts_code,trade_date,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,total_mv,circ_mv"
        )

        logger.info(f"获取到 {len(df)} 条基本面记录")
        return df
```

**Step 4: 运行测试验证通过**

```bash
pytest tests/test_tushare_collector.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/data_collector/tushare_collector.py tests/test_tushare_collector.py
git commit -m "feat: add TuShareCollector with daily/index/money_flow support"
```

---

### Task 7: AkShare采集器（备用源）

**Files:**
- Create: `src/data_collector/akshare_collector.py`
- Create: `tests/test_akshare_collector.py`

**Step 1: 写失败测试**

`tests/test_akshare_collector.py`:
```python
import pytest
import pandas as pd
from unittest.mock import patch
from src.data_collector.akshare_collector import AkShareCollector


class TestAkShareCollector:
    @patch("src.data_collector.akshare_collector.ak")
    def test_fetch_stock_list(self, mock_ak):
        """测试获取股票列表"""
        mock_ak.stock_info_a_code_name.return_value = pd.DataFrame({
            "code": ["000001", "600000"],
            "name": ["平安银行", "浦发银行"],
        })

        collector = AkShareCollector()
        df = collector.get_stock_list()

        assert len(df) == 2
        assert "ts_code" in df.columns  # 统一转换为ts_code格式

    @patch("src.data_collector.akshare_collector.ak")
    def test_fetch_daily(self, mock_ak):
        """测试获取日线数据"""
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame({
            "日期": ["2025-01-14"],
            "开盘": [10.0],
            "收盘": [10.2],
            "最高": [10.5],
            "最低": [9.8],
            "成交量": [1000000],
            "成交额": [10200000.0],
        })

        collector = AkShareCollector()
        df = collector.get_daily("000001.SZ", "20250101", "20250114")

        assert len(df) == 1
        # 验证字段名已转换为统一格式
        assert "close" in df.columns
        assert "trade_date" in df.columns

    @patch("src.data_collector.akshare_collector.ak")
    def test_fetch_index_daily(self, mock_ak):
        """测试获取指数日线数据"""
        mock_ak.stock_zh_index_daily.return_value = pd.DataFrame({
            "date": ["2025-01-14"],
            "open": [3180.0],
            "high": [3220.0],
            "low": [3170.0],
            "close": [3200.0],
            "volume": [300000000000.0],
        })

        collector = AkShareCollector()
        df = collector.get_index_daily("000001.SH", "20250101", "20250114")

        assert len(df) == 1
        assert df.iloc[0]["close"] == 3200.0
```

**Step 2: 运行测试验证失败**

```bash
pytest tests/test_akshare_collector.py -v
```
Expected: FAIL

**Step 3: 实现AkShare采集器**

`src/data_collector/akshare_collector.py`:
```python
"""AkShare数据采集器（备用数据源）"""
import time
import pandas as pd
import akshare as ak

from src.data_collector.base_collector import BaseCollector
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AkShareCollector(BaseCollector):
    """AkShare数据采集器

    作为TuShare的备用数据源。AkShare是免费的，但数据更新可能稍慢。

    API文档: https://akshare.akfamily.xyz/
    """

    def __init__(
        self,
        request_interval: float = 0.5,
        max_retries: int = 3,
    ):
        """初始化AkShare采集器

        Args:
            request_interval: 请求间隔(秒)
            max_retries: 最大重试次数
        """
        super().__init__(max_retries=max_retries)
        self.request_interval = request_interval

    def _rate_limit(self):
        """请求频率限制"""
        time.sleep(self.request_interval)

    def _convert_code_to_ts(self, code: str) -> str:
        """将纯数字代码转换为ts_code格式

        Args:
            code: 纯数字代码 (如 000001)

        Returns:
            ts_code格式 (如 000001.SZ)
        """
        if code.startswith("6"):
            return f"{code}.SH"
        else:
            return f"{code}.SZ"

    def _convert_ts_to_code(self, ts_code: str) -> str:
        """将ts_code格式转换为纯数字代码

        Args:
            ts_code: ts_code格式 (如 000001.SZ)

        Returns:
            纯数字代码 (如 000001)
        """
        return ts_code.split(".")[0]

    def _fetch_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表

        Returns:
            DataFrame with columns: ts_code, name
        """
        logger.info("正在通过AkShare获取A股股票列表...")
        self._rate_limit()

        df = ak.stock_info_a_code_name()

        # 转换为统一格式
        df["ts_code"] = df["code"].apply(self._convert_code_to_ts)
        df = df.rename(columns={"name": "name"})
        df = df[["ts_code", "name"]]

        # AkShare不提供industry字段，设为空
        df["industry"] = ""
        df["market"] = ""
        df["list_date"] = ""

        logger.info(f"获取到 {len(df)} 只股票")
        return df

    def _fetch_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取单只股票日线数据

        Args:
            ts_code: 股票代码 (如 000001.SZ)
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)

        Returns:
            日线数据（统一字段格式）
        """
        self._rate_limit()

        code = self._convert_ts_to_code(ts_code)

        # AkShare使用 YYYY-MM-DD 格式
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",  # 前复权
        )

        if df.empty:
            return pd.DataFrame()

        # 转换为统一格式
        df = df.rename(columns={
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "vol",
            "成交额": "amount",
        })

        # 转换日期格式
        df["trade_date"] = df["trade_date"].str.replace("-", "")
        df["ts_code"] = ts_code

        return df[["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]]

    def _fetch_index_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取指数日线数据

        Args:
            ts_code: 指数代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            指数日线数据
        """
        self._rate_limit()

        # AkShare指数代码映射
        index_map = {
            "000001.SH": "sh000001",  # 上证指数
            "399001.SZ": "sz399001",  # 深证成指
            "399006.SZ": "sz399006",  # 创业板指
        }

        ak_code = index_map.get(ts_code)
        if not ak_code:
            logger.warning(f"未知指数代码: {ts_code}")
            return pd.DataFrame()

        df = ak.stock_zh_index_daily(symbol=ak_code)

        if df.empty:
            return pd.DataFrame()

        # 过滤日期范围
        df["trade_date"] = df["date"].astype(str).str.replace("-", "")
        df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]

        df["ts_code"] = ts_code

        return df[["ts_code", "trade_date", "open", "high", "low", "close", "volume"]]

    def _fetch_money_flow(self, trade_date: str) -> pd.DataFrame:
        """获取资金流数据

        注意: AkShare的资金流接口与TuShare不同，此处返回空DataFrame
        """
        logger.warning("AkShare资金流数据接口不兼容，请使用TuShare")
        return pd.DataFrame()
```

**Step 4: 运行测试验证通过**

```bash
pytest tests/test_akshare_collector.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/data_collector/akshare_collector.py tests/test_akshare_collector.py
git commit -m "feat: add AkShareCollector as fallback data source"
```

---

### Task 8: 采集器管理器（多源切换）

**Files:**
- Create: `src/data_collector/collector_manager.py`
- Create: `tests/test_collector_manager.py`

**Step 1: 写失败测试**

`tests/test_collector_manager.py`:
```python
import pytest
import pandas as pd
from unittest.mock import Mock, patch
from src.data_collector.collector_manager import CollectorManager
from src.data_collector.base_collector import CollectorError


class TestCollectorManager:
    def test_use_primary_source_when_available(self):
        """测试优先使用主数据源"""
        mock_primary = Mock()
        mock_fallback = Mock()

        mock_primary.get_stock_list.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "name": ["平安银行"],
        })

        manager = CollectorManager(
            primary=mock_primary,
            fallbacks=[mock_fallback],
        )

        df = manager.get_stock_list()

        assert len(df) == 1
        mock_primary.get_stock_list.assert_called_once()
        mock_fallback.get_stock_list.assert_not_called()

    def test_fallback_when_primary_fails(self):
        """测试主数据源失败时切换到备用源"""
        mock_primary = Mock()
        mock_fallback = Mock()

        mock_primary.get_stock_list.side_effect = CollectorError("API Error")
        mock_fallback.get_stock_list.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "name": ["平安银行"],
        })

        manager = CollectorManager(
            primary=mock_primary,
            fallbacks=[mock_fallback],
        )

        df = manager.get_stock_list()

        assert len(df) == 1
        mock_primary.get_stock_list.assert_called_once()
        mock_fallback.get_stock_list.assert_called_once()

    def test_all_sources_fail_raises_error(self):
        """测试所有数据源都失败时抛出异常"""
        mock_primary = Mock()
        mock_fallback = Mock()

        mock_primary.get_stock_list.side_effect = CollectorError("Primary Error")
        mock_fallback.get_stock_list.side_effect = CollectorError("Fallback Error")

        manager = CollectorManager(
            primary=mock_primary,
            fallbacks=[mock_fallback],
        )

        with pytest.raises(CollectorError):
            manager.get_stock_list()

    def test_get_daily_with_fallback(self):
        """测试获取日线数据的容灾切换"""
        mock_primary = Mock()
        mock_fallback = Mock()

        mock_primary.get_daily_all.side_effect = CollectorError("Rate limit")
        mock_fallback.get_daily_all.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "close": [10.2],
        })

        manager = CollectorManager(
            primary=mock_primary,
            fallbacks=[mock_fallback],
        )

        df = manager.get_daily_all("20250114")

        assert len(df) == 1
```

**Step 2: 运行测试验证失败**

```bash
pytest tests/test_collector_manager.py -v
```
Expected: FAIL

**Step 3: 实现采集器管理器**

`src/data_collector/collector_manager.py`:
```python
"""数据采集器管理器，处理多源切换和容灾"""
from typing import List, Optional
import pandas as pd

from src.data_collector.base_collector import BaseCollector, CollectorError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CollectorManager:
    """数据采集器管理器

    管理多个数据源，实现自动容灾切换。
    优先使用主数据源，失败时依次尝试备用源。
    """

    def __init__(
        self,
        primary: BaseCollector,
        fallbacks: Optional[List[BaseCollector]] = None
    ):
        """初始化管理器

        Args:
            primary: 主数据源
            fallbacks: 备用数据源列表
        """
        self.primary = primary
        self.fallbacks = fallbacks or []
        self._all_sources = [primary] + self.fallbacks

    def _try_sources(self, method_name: str, *args, **kwargs) -> pd.DataFrame:
        """尝试从多个数据源获取数据

        Args:
            method_name: 要调用的方法名
            *args, **kwargs: 方法参数

        Returns:
            获取到的数据

        Raises:
            CollectorError: 所有数据源都失败
        """
        errors = []

        for i, source in enumerate(self._all_sources):
            source_name = source.__class__.__name__
            try:
                method = getattr(source, method_name)
                result = method(*args, **kwargs)

                if i > 0:
                    logger.info(f"使用备用数据源 {source_name} 成功")

                return result

            except (CollectorError, Exception) as e:
                errors.append(f"{source_name}: {e}")
                logger.warning(f"数据源 {source_name} 失败: {e}")
                continue

        # 所有数据源都失败
        error_msg = "所有数据源都失败:\n" + "\n".join(errors)
        logger.error(error_msg)
        raise CollectorError(error_msg)

    def get_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表"""
        return self._try_sources("get_stock_list")

    def get_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取单只股票日线数据"""
        return self._try_sources("get_daily", ts_code, start_date, end_date)

    def get_daily_all(self, trade_date: str) -> pd.DataFrame:
        """获取指定交易日全市场日线数据"""
        return self._try_sources("get_daily_all", trade_date)

    def get_index_daily(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取指数日线数据"""
        return self._try_sources("get_index_daily", ts_code, start_date, end_date)

    def get_money_flow(self, trade_date: str) -> pd.DataFrame:
        """获取资金流数据"""
        return self._try_sources("get_money_flow", trade_date)


def create_collector_manager(config) -> CollectorManager:
    """根据配置创建采集器管理器

    Args:
        config: Config对象

    Returns:
        配置好的CollectorManager
    """
    from src.data_collector.tushare_collector import TuShareCollector
    from src.data_collector.akshare_collector import AkShareCollector

    # 创建主数据源
    primary_source = config.get("collector.primary_source", "tushare")

    if primary_source == "tushare":
        token = config.get("tushare.token")
        if not token:
            raise ValueError("TuShare token未配置")
        primary = TuShareCollector(
            token=token,
            request_interval=config.get("collector.request_interval", 0.3),
        )
    else:
        primary = AkShareCollector()

    # 创建备用数据源
    fallbacks = []
    fallback_sources = config.get("collector.fallback_sources", [])

    for source in fallback_sources:
        if source == "akshare" and primary_source != "akshare":
            fallbacks.append(AkShareCollector())
        # baostock暂不实现，可后续添加

    return CollectorManager(primary=primary, fallbacks=fallbacks)
```

**Step 4: 运行测试验证通过**

```bash
pytest tests/test_collector_manager.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/data_collector/collector_manager.py tests/test_collector_manager.py
git commit -m "feat: add CollectorManager for multi-source failover"
```

---

### Task 9: 新闻爬虫

**Files:**
- Create: `src/data_collector/news_crawler.py`
- Create: `tests/test_news_crawler.py`

**Step 1: 写失败测试**

`tests/test_news_crawler.py`:
```python
import pytest
from unittest.mock import patch, Mock
from src.data_collector.news_crawler import NewsCrawler, NewsItem


class TestNewsCrawler:
    @patch("src.data_collector.news_crawler.requests")
    def test_crawl_eastmoney_news(self, mock_requests):
        """测试爬取东方财富新闻"""
        mock_response = Mock()
        mock_response.text = """
        <html>
        <body>
            <div class="news-item">
                <a href="/news/1.html">A股三大指数集体高开</a>
            </div>
            <div class="news-item">
                <a href="/news/2.html">北向资金净流入超50亿</a>
            </div>
        </body>
        </html>
        """
        mock_response.status_code = 200
        mock_requests.get.return_value = mock_response

        crawler = NewsCrawler()
        news_list = crawler.crawl_eastmoney(max_count=5)

        assert isinstance(news_list, list)

    def test_analyze_sentiment_positive(self):
        """测试正面新闻情绪分析"""
        crawler = NewsCrawler()

        score = crawler.analyze_sentiment("A股三大指数集体大涨 北向资金大举流入")

        assert score > 50  # 正面情绪分数应该大于50

    def test_analyze_sentiment_negative(self):
        """测试负面新闻情绪分析"""
        crawler = NewsCrawler()

        score = crawler.analyze_sentiment("A股暴跌 千股跌停 恐慌情绪蔓延")

        assert score < 50  # 负面情绪分数应该小于50

    def test_analyze_sentiment_neutral(self):
        """测试中性新闻情绪分析"""
        crawler = NewsCrawler()

        score = crawler.analyze_sentiment("央行公布最新货币政策报告")

        assert 40 <= score <= 60  # 中性情绪分数应该在40-60之间

    def test_news_item_dataclass(self):
        """测试NewsItem数据类"""
        item = NewsItem(
            title="测试新闻",
            source="eastmoney",
            sentiment_score=65.0,
            keywords="测试,新闻",
        )

        assert item.title == "测试新闻"
        assert item.sentiment_score == 65.0
```

**Step 2: 运行测试验证失败**

```bash
pytest tests/test_news_crawler.py -v
```
Expected: FAIL

**Step 3: 实现新闻爬虫**

`src/data_collector/news_crawler.py`:
```python
"""财经新闻爬虫和情绪分析"""
import re
from dataclasses import dataclass
from typing import List, Optional
import requests
from bs4 import BeautifulSoup

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    source: str
    sentiment_score: float
    keywords: str = ""
    url: str = ""


class NewsCrawler:
    """财经新闻爬虫

    爬取主流财经网站的新闻标题，并进行简单的情绪分析。
    """

    # 情绪关键词
    POSITIVE_KEYWORDS = [
        "大涨", "涨停", "突破", "新高", "利好", "上涨", "反弹",
        "流入", "增持", "买入", "牛市", "暴涨", "飙升", "走强",
        "提振", "政策支持", "刺激", "红盘", "翻红",
    ]

    NEGATIVE_KEYWORDS = [
        "暴跌", "跌停", "跳水", "崩盘", "恐慌", "下跌", "回落",
        "流出", "减持", "卖出", "熊市", "大跌", "走弱", "杀跌",
        "监管", "调查", "处罚", "绿盘", "翻绿", "破位",
    ]

    def __init__(self, timeout: int = 10):
        """初始化爬虫

        Args:
            timeout: 请求超时时间(秒)
        """
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }

    def crawl_eastmoney(self, max_count: int = 20) -> List[NewsItem]:
        """爬取东方财富财经新闻

        Args:
            max_count: 最大爬取数量

        Returns:
            新闻列表
        """
        logger.info("正在爬取东方财富新闻...")

        url = "https://finance.eastmoney.com/a/cywjh.html"

        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout
            )
            response.encoding = "utf-8"

            soup = BeautifulSoup(response.text, "lxml")

            news_list = []
            # 东方财富新闻列表的选择器（可能需要根据实际页面调整）
            for item in soup.select("div.text a, li.title a")[:max_count]:
                title = item.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                href = item.get("href", "")
                score = self.analyze_sentiment(title)
                keywords = self._extract_keywords(title)

                news_list.append(NewsItem(
                    title=title,
                    source="eastmoney",
                    sentiment_score=score,
                    keywords=keywords,
                    url=href,
                ))

            logger.info(f"爬取到 {len(news_list)} 条新闻")
            return news_list

        except Exception as e:
            logger.error(f"爬取东方财富新闻失败: {e}")
            return []

    def crawl_sina(self, max_count: int = 20) -> List[NewsItem]:
        """爬取新浪财经新闻

        Args:
            max_count: 最大爬取数量

        Returns:
            新闻列表
        """
        logger.info("正在爬取新浪财经新闻...")

        url = "https://finance.sina.com.cn/stock/"

        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout
            )
            response.encoding = "utf-8"

            soup = BeautifulSoup(response.text, "lxml")

            news_list = []
            for item in soup.select("a[href*='/stock/']")[:max_count]:
                title = item.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                href = item.get("href", "")
                score = self.analyze_sentiment(title)
                keywords = self._extract_keywords(title)

                news_list.append(NewsItem(
                    title=title,
                    source="sina",
                    sentiment_score=score,
                    keywords=keywords,
                    url=href,
                ))

            logger.info(f"爬取到 {len(news_list)} 条新闻")
            return news_list

        except Exception as e:
            logger.error(f"爬取新浪财经新闻失败: {e}")
            return []

    def crawl_all(self, max_count: int = 20) -> List[NewsItem]:
        """爬取所有数据源的新闻

        Args:
            max_count: 每个数据源的最大爬取数量

        Returns:
            合并后的新闻列表
        """
        all_news = []

        # 东方财富
        all_news.extend(self.crawl_eastmoney(max_count))

        # 新浪财经
        all_news.extend(self.crawl_sina(max_count))

        # 去重（基于标题）
        seen = set()
        unique_news = []
        for news in all_news:
            if news.title not in seen:
                seen.add(news.title)
                unique_news.append(news)

        return unique_news

    def analyze_sentiment(self, text: str) -> float:
        """分析文本情绪

        使用简单的关键词匹配方法。

        Args:
            text: 新闻标题或内容

        Returns:
            情绪分数 (0-100, 50为中性)
        """
        positive_count = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in text)
        negative_count = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in text)

        # 基准分50
        score = 50.0

        # 正面关键词加分，负面减分
        score += positive_count * 8
        score -= negative_count * 10

        # 限制在0-100范围
        return max(0, min(100, score))

    def _extract_keywords(self, text: str) -> str:
        """提取关键词

        Args:
            text: 文本

        Returns:
            逗号分隔的关键词
        """
        keywords = []

        for kw in self.POSITIVE_KEYWORDS + self.NEGATIVE_KEYWORDS:
            if kw in text:
                keywords.append(kw)

        return ",".join(keywords[:5])  # 最多5个关键词

    def get_overall_sentiment(self, news_list: List[NewsItem]) -> float:
        """计算整体市场情绪

        Args:
            news_list: 新闻列表

        Returns:
            整体情绪分数 (0-100)
        """
        if not news_list:
            return 50.0

        total_score = sum(n.sentiment_score for n in news_list)
        return total_score / len(news_list)
```

**Step 4: 运行测试验证通过**

```bash
pytest tests/test_news_crawler.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/data_collector/news_crawler.py tests/test_news_crawler.py
git commit -m "feat: add NewsCrawler with sentiment analysis"
```

---

## 模块4: 数据更新Pipeline

### Task 10: 数据更新Pipeline

**Files:**
- Create: `src/data_pipeline/daily_updater.py`
- Create: `tests/test_daily_updater.py`

**Step 1: 写失败测试**

`tests/test_daily_updater.py`:
```python
import pytest
import pandas as pd
from unittest.mock import Mock, patch
from datetime import date
from src.data_pipeline.daily_updater import DailyUpdater


class TestDailyUpdater:
    def test_update_daily_data(self, tmp_path):
        """测试更新日线数据"""
        # Mock依赖
        mock_collector = Mock()
        mock_storage = Mock()
        mock_db = Mock()

        mock_collector.get_daily_all.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "trade_date": ["20250114", "20250114"],
            "open": [10.0, 8.0],
            "high": [10.5, 8.5],
            "low": [9.8, 7.9],
            "close": [10.2, 8.2],
            "vol": [1000000, 800000],
            "amount": [10200000, 6560000],
        })

        mock_db.get_latest_update.return_value = {
            "trade_date": "20250113",
        }

        updater = DailyUpdater(
            collector=mock_collector,
            storage=mock_storage,
            database=mock_db,
        )

        result = updater.update_daily("20250114")

        assert result["success"] is True
        assert result["record_count"] == 2
        mock_storage.append_daily.assert_called_once()
        mock_db.log_update.assert_called_once()

    def test_skip_if_already_updated(self, tmp_path):
        """测试跳过已更新的日期"""
        mock_collector = Mock()
        mock_storage = Mock()
        mock_db = Mock()

        mock_db.get_latest_update.return_value = {
            "trade_date": "20250114",
            "status": "success",
        }

        updater = DailyUpdater(
            collector=mock_collector,
            storage=mock_storage,
            database=mock_db,
        )

        result = updater.update_daily("20250114")

        assert result["skipped"] is True
        mock_collector.get_daily_all.assert_not_called()

    def test_update_index_data(self):
        """测试更新指数数据"""
        mock_collector = Mock()
        mock_storage = Mock()
        mock_db = Mock()

        mock_collector.get_index_daily.return_value = pd.DataFrame({
            "ts_code": ["000001.SH"],
            "trade_date": ["20250114"],
            "close": [3200.0],
        })

        updater = DailyUpdater(
            collector=mock_collector,
            storage=mock_storage,
            database=mock_db,
        )

        result = updater.update_index("20250114")

        assert result["success"] is True

    def test_full_daily_update(self):
        """测试完整的每日更新流程"""
        mock_collector = Mock()
        mock_storage = Mock()
        mock_db = Mock()

        mock_collector.get_daily_all.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "close": [10.2],
        })
        mock_collector.get_index_daily.return_value = pd.DataFrame({
            "ts_code": ["000001.SH"],
            "trade_date": ["20250114"],
            "close": [3200.0],
        })
        mock_collector.get_money_flow.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20250114"],
            "net_mf_vol": [20000.0],
        })

        mock_db.get_latest_update.return_value = None

        updater = DailyUpdater(
            collector=mock_collector,
            storage=mock_storage,
            database=mock_db,
        )

        results = updater.run_full_update("20250114")

        assert "daily" in results
        assert "index" in results
        assert "money_flow" in results
```

**Step 2: 运行测试验证失败**

```bash
mkdir -p src/data_pipeline
touch src/data_pipeline/__init__.py
pytest tests/test_daily_updater.py -v
```
Expected: FAIL

**Step 3: 实现数据更新Pipeline**

`src/data_pipeline/__init__.py`:
```python
# Data pipeline module
```

`src/data_pipeline/daily_updater.py`:
```python
"""每日数据更新Pipeline"""
from typing import Dict, Any, Optional, List
from datetime import date, datetime, timedelta
import pandas as pd

from src.data_collector.collector_manager import CollectorManager
from src.data_storage.parquet_storage import ParquetStorage
from src.data_storage.database import Database
from src.data_collector.news_crawler import NewsCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)


# 主要指数代码
MAJOR_INDICES = [
    "000001.SH",  # 上证指数
    "399001.SZ",  # 深证成指
    "399006.SZ",  # 创业板指
    "000016.SH",  # 上证50
    "000300.SH",  # 沪深300
]


class DailyUpdater:
    """每日数据更新器

    负责协调数据采集、存储和日志记录。
    """

    def __init__(
        self,
        collector: CollectorManager,
        storage: ParquetStorage,
        database: Database,
        news_crawler: Optional[NewsCrawler] = None,
    ):
        """初始化更新器

        Args:
            collector: 数据采集管理器
            storage: Parquet存储管理器
            database: SQLite数据库
            news_crawler: 新闻爬虫（可选）
        """
        self.collector = collector
        self.storage = storage
        self.database = database
        self.news_crawler = news_crawler or NewsCrawler()

    def _is_already_updated(self, data_type: str, trade_date: str) -> bool:
        """检查数据是否已更新

        Args:
            data_type: 数据类型
            trade_date: 交易日期

        Returns:
            是否已更新
        """
        latest = self.database.get_latest_update(data_type)
        if latest and latest["trade_date"] >= trade_date and latest["status"] == "success":
            return True
        return False

    def update_daily(self, trade_date: str, force: bool = False) -> Dict[str, Any]:
        """更新日线数据

        Args:
            trade_date: 交易日期 (YYYYMMDD)
            force: 强制更新（忽略已更新检查）

        Returns:
            更新结果
        """
        if not force and self._is_already_updated("daily", trade_date):
            logger.info(f"日线数据 {trade_date} 已更新，跳过")
            return {"skipped": True, "trade_date": trade_date}

        logger.info(f"开始更新日线数据: {trade_date}")

        try:
            # 获取全市场日线数据
            df = self.collector.get_daily_all(trade_date)

            if df.empty:
                logger.warning(f"未获取到 {trade_date} 的日线数据")
                return {"success": False, "error": "No data", "trade_date": trade_date}

            # 保存到Parquet
            year = trade_date[:4]
            self.storage.append_daily(year, df)

            # 记录日志
            self.database.log_update(
                data_type="daily",
                trade_date=trade_date,
                record_count=len(df),
                status="success",
            )

            logger.info(f"日线数据更新完成: {len(df)} 条记录")
            return {
                "success": True,
                "trade_date": trade_date,
                "record_count": len(df),
            }

        except Exception as e:
            logger.error(f"日线数据更新失败: {e}")
            self.database.log_update(
                data_type="daily",
                trade_date=trade_date,
                record_count=0,
                status="failed",
                error_msg=str(e),
            )
            return {"success": False, "error": str(e), "trade_date": trade_date}

    def update_index(self, trade_date: str, force: bool = False) -> Dict[str, Any]:
        """更新指数数据

        Args:
            trade_date: 交易日期
            force: 强制更新

        Returns:
            更新结果
        """
        if not force and self._is_already_updated("index", trade_date):
            logger.info(f"指数数据 {trade_date} 已更新，跳过")
            return {"skipped": True, "trade_date": trade_date}

        logger.info(f"开始更新指数数据: {trade_date}")

        try:
            all_data = []

            for index_code in MAJOR_INDICES:
                df = self.collector.get_index_daily(
                    index_code,
                    start_date=trade_date,
                    end_date=trade_date
                )
                if not df.empty:
                    all_data.append(df)

            if not all_data:
                logger.warning(f"未获取到 {trade_date} 的指数数据")
                return {"success": False, "error": "No data", "trade_date": trade_date}

            combined = pd.concat(all_data, ignore_index=True)

            year = trade_date[:4]
            self.storage.append_index(year, combined)

            self.database.log_update(
                data_type="index",
                trade_date=trade_date,
                record_count=len(combined),
                status="success",
            )

            logger.info(f"指数数据更新完成: {len(combined)} 条记录")
            return {
                "success": True,
                "trade_date": trade_date,
                "record_count": len(combined),
            }

        except Exception as e:
            logger.error(f"指数数据更新失败: {e}")
            self.database.log_update(
                data_type="index",
                trade_date=trade_date,
                record_count=0,
                status="failed",
                error_msg=str(e),
            )
            return {"success": False, "error": str(e), "trade_date": trade_date}

    def update_money_flow(self, trade_date: str, force: bool = False) -> Dict[str, Any]:
        """更新资金流数据

        Args:
            trade_date: 交易日期
            force: 强制更新

        Returns:
            更新结果
        """
        if not force and self._is_already_updated("money_flow", trade_date):
            logger.info(f"资金流数据 {trade_date} 已更新，跳过")
            return {"skipped": True, "trade_date": trade_date}

        logger.info(f"开始更新资金流数据: {trade_date}")

        try:
            df = self.collector.get_money_flow(trade_date)

            if df.empty:
                logger.warning(f"未获取到 {trade_date} 的资金流数据")
                return {"success": False, "error": "No data", "trade_date": trade_date}

            year = trade_date[:4]
            self.storage.append_money_flow(year, df)

            self.database.log_update(
                data_type="money_flow",
                trade_date=trade_date,
                record_count=len(df),
                status="success",
            )

            logger.info(f"资金流数据更新完成: {len(df)} 条记录")
            return {
                "success": True,
                "trade_date": trade_date,
                "record_count": len(df),
            }

        except Exception as e:
            logger.error(f"资金流数据更新失败: {e}")
            self.database.log_update(
                data_type="money_flow",
                trade_date=trade_date,
                record_count=0,
                status="failed",
                error_msg=str(e),
            )
            return {"success": False, "error": str(e), "trade_date": trade_date}

    def update_news(self, trade_date: str) -> Dict[str, Any]:
        """更新新闻数据

        Args:
            trade_date: 交易日期

        Returns:
            更新结果
        """
        logger.info(f"开始爬取新闻: {trade_date}")

        try:
            news_list = self.news_crawler.crawl_all(max_count=20)

            if not news_list:
                logger.warning("未爬取到新闻")
                return {"success": False, "error": "No news", "trade_date": trade_date}

            # 保存到数据库
            news_data = [
                {
                    "trade_date": trade_date,
                    "title": n.title,
                    "source": n.source,
                    "sentiment_score": n.sentiment_score,
                    "keywords": n.keywords,
                }
                for n in news_list
            ]
            self.database.save_news_sentiment(news_data)

            # 计算整体情绪
            overall_sentiment = self.news_crawler.get_overall_sentiment(news_list)

            logger.info(f"新闻更新完成: {len(news_list)} 条, 整体情绪: {overall_sentiment:.1f}")
            return {
                "success": True,
                "trade_date": trade_date,
                "news_count": len(news_list),
                "overall_sentiment": overall_sentiment,
            }

        except Exception as e:
            logger.error(f"新闻更新失败: {e}")
            return {"success": False, "error": str(e), "trade_date": trade_date}

    def run_full_update(self, trade_date: str, force: bool = False) -> Dict[str, Any]:
        """运行完整的每日更新

        Args:
            trade_date: 交易日期
            force: 强制更新

        Returns:
            所有更新的结果
        """
        logger.info(f"========== 开始每日全量更新: {trade_date} ==========")

        results = {}

        # 1. 更新日线数据
        results["daily"] = self.update_daily(trade_date, force)

        # 2. 更新指数数据
        results["index"] = self.update_index(trade_date, force)

        # 3. 更新资金流数据
        results["money_flow"] = self.update_money_flow(trade_date, force)

        # 4. 更新新闻
        results["news"] = self.update_news(trade_date)

        # 统计结果
        success_count = sum(
            1 for r in results.values()
            if r.get("success") or r.get("skipped")
        )

        logger.info(f"========== 更新完成: {success_count}/4 成功 ==========")

        return results

    def update_stock_list(self) -> Dict[str, Any]:
        """更新股票列表

        Returns:
            更新结果
        """
        logger.info("开始更新股票列表...")

        try:
            df = self.collector.get_stock_list()

            if df.empty:
                return {"success": False, "error": "No data"}

            stocks = df.to_dict("records")
            self.database.upsert_stock_list(stocks)

            logger.info(f"股票列表更新完成: {len(stocks)} 只")
            return {"success": True, "stock_count": len(stocks)}

        except Exception as e:
            logger.error(f"股票列表更新失败: {e}")
            return {"success": False, "error": str(e)}
```

**Step 4: 运行测试验证通过**

```bash
pytest tests/test_daily_updater.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/data_pipeline/ tests/test_daily_updater.py
git commit -m "feat: add DailyUpdater pipeline for coordinated data updates"
```

---

### Task 11: 主入口脚本

**Files:**
- Create: `src/main.py`

**Step 1: 实现主入口**

`src/main.py`:
```python
"""StockAgent主入口"""
import argparse
import os
import sys
from datetime import date, datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.config import Config
from src.utils.logger import setup_logger, get_logger
from src.data_storage.database import Database
from src.data_storage.parquet_storage import ParquetStorage
from src.data_collector.collector_manager import create_collector_manager
from src.data_pipeline.daily_updater import DailyUpdater


def init_system(config_path: str = "config/config.yaml"):
    """初始化系统组件

    Args:
        config_path: 配置文件路径

    Returns:
        (config, collector, storage, database, updater)
    """
    # 加载配置
    config = Config(config_path)

    # 设置日志
    setup_logger(
        log_file=config.get("logging.file", "logs/stockagent.log"),
        level=config.get("logging.level", "INFO"),
    )
    logger = get_logger(__name__)
    logger.info("系统初始化中...")

    # 初始化存储
    storage = ParquetStorage(config.get("storage.parquet_dir", "data/market_data"))

    # 初始化数据库
    db_path = config.get("storage.sqlite_db", "data/business.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    database = Database(db_path)
    database.init_tables()

    # 初始化采集器
    collector = create_collector_manager(config)

    # 初始化更新器
    updater = DailyUpdater(
        collector=collector,
        storage=storage,
        database=database,
    )

    logger.info("系统初始化完成")
    return config, collector, storage, database, updater


def cmd_update(args):
    """执行数据更新命令"""
    config, collector, storage, database, updater = init_system(args.config)
    logger = get_logger(__name__)

    trade_date = args.date or datetime.now().strftime("%Y%m%d")

    if args.type == "all":
        results = updater.run_full_update(trade_date, force=args.force)
        for data_type, result in results.items():
            status = "成功" if result.get("success") or result.get("skipped") else "失败"
            logger.info(f"  {data_type}: {status}")
    elif args.type == "daily":
        updater.update_daily(trade_date, force=args.force)
    elif args.type == "index":
        updater.update_index(trade_date, force=args.force)
    elif args.type == "money_flow":
        updater.update_money_flow(trade_date, force=args.force)
    elif args.type == "news":
        updater.update_news(trade_date)
    elif args.type == "stock_list":
        updater.update_stock_list()


def cmd_init(args):
    """初始化系统"""
    config, collector, storage, database, updater = init_system(args.config)
    logger = get_logger(__name__)

    logger.info("正在初始化股票列表...")
    updater.update_stock_list()

    logger.info("系统初始化完成！")
    logger.info("下一步: 运行 'python src/main.py update --date YYYYMMDD' 更新数据")


def main():
    parser = argparse.ArgumentParser(description="StockAgent - A股量化交易系统")
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="配置文件路径"
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # init命令
    init_parser = subparsers.add_parser("init", help="初始化系统")
    init_parser.set_defaults(func=cmd_init)

    # update命令
    update_parser = subparsers.add_parser("update", help="更新数据")
    update_parser.add_argument(
        "--type",
        choices=["all", "daily", "index", "money_flow", "news", "stock_list"],
        default="all",
        help="更新类型"
    )
    update_parser.add_argument(
        "--date",
        help="交易日期 (YYYYMMDD), 默认为今天"
    )
    update_parser.add_argument(
        "--force",
        action="store_true",
        help="强制更新（忽略已更新检查）"
    )
    update_parser.set_defaults(func=cmd_update)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add src/main.py
git commit -m "feat: add main entry script with CLI commands"
```

---

## 最终验证

### Task 12: 集成测试

**Step 1: 运行所有测试**

```bash
pytest tests/ -v --cov=src --cov-report=term-missing
```

**Step 2: 检查覆盖率**

目标覆盖率 > 80%

**Step 3: 创建示例配置**

```bash
cp config/config.yaml.example config/config.yaml
# 编辑config.yaml，填入真实的TuShare token
```

**Step 4: 测试初始化**

```bash
python src/main.py init --config config/config.yaml
```

**Step 5: 最终Commit**

```bash
git add -A
git commit -m "chore: complete phase 1 data layer implementation"
```

---

## 交付物清单

完成本阶段后，你将拥有：

1. **配置系统** (`src/utils/`)
   - [x] config.py - 配置加载器
   - [x] logger.py - 日志工具

2. **数据存储** (`src/data_storage/`)
   - [x] database.py - SQLite数据库管理
   - [x] parquet_storage.py - Parquet文件存储

3. **数据采集** (`src/data_collector/`)
   - [x] base_collector.py - 采集器基类
   - [x] tushare_collector.py - TuShare采集器
   - [x] akshare_collector.py - AkShare采集器（备用）
   - [x] collector_manager.py - 多源管理器
   - [x] news_crawler.py - 新闻爬虫

4. **数据Pipeline** (`src/data_pipeline/`)
   - [x] daily_updater.py - 每日更新器

5. **主程序** (`src/main.py`)
   - [x] CLI命令行接口

6. **测试** (`tests/`)
   - [x] 所有模块的单元测试
   - [x] 覆盖率 > 80%
