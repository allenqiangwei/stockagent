"""Application configuration — loads from config/config.yaml with env overrides."""

import os
from pathlib import Path
from functools import lru_cache

import yaml
from pydantic import BaseModel


_PROJECT_ROOT = Path(__file__).parent.parent


class DataSourceConfig(BaseModel):
    tushare_token: str = ""
    fallback_enabled: bool = True
    request_interval: float = 0.3
    # Per-category data source preference: "tushare" | "tdx"
    # TDX: free, no rate limit, TCP direct — best for bulk OHLCV
    # TuShare: has daily_basic (PE/PB), trade_cal, batch-by-date — best for fundamentals
    realtime_quotes: str = "tdx"
    historical_daily: str = "tdx"
    index_data: str = "tdx"
    sector_data: str = "tdx"
    money_flow: str = "tushare"      # TDX has no money flow data
    stock_list: str = "tdx"
    daily_batch: str = "tushare"     # Batch all-stock-by-date: TuShare only (TDX needs per-stock)
    fundamentals: str = "tushare"    # PE/PB/MV/turnover: TuShare only
    trade_calendar: str = "tushare"  # Trading calendar: TuShare only
    tushare_rate_limit: int = 190


class DatabaseConfig(BaseModel):
    url: str = ""


class DeepSeekConfig(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"


class QwenConfig(BaseModel):
    """Local Qwen LLM (OpenAI-compatible API)."""
    api_key: str = "not-needed"
    base_url: str = "http://192.168.100.172:8680/v1"
    model: str = "qwen3.5-35b-a3b"


class AILabConfig(BaseModel):
    """Scoring weights for AI Lab experiments (must sum to 1.0)."""
    weight_return: float = 0.30
    weight_drawdown: float = 0.25
    weight_sharpe: float = 0.25
    weight_plr: float = 0.20


class AuthConfig(BaseModel):
    """API key authentication settings."""
    enabled: bool = True
    bypass_local: bool = True  # Skip auth for 127.0.0.1 / ::1


class Settings(BaseModel):
    project_root: Path = _PROJECT_ROOT
    data_sources: DataSourceConfig = DataSourceConfig()
    database: DatabaseConfig = DatabaseConfig()
    deepseek: DeepSeekConfig = DeepSeekConfig()
    qwen: QwenConfig = QwenConfig()
    ai_lab: AILabConfig = AILabConfig()
    auth: AuthConfig = AuthConfig()
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    """Load settings from config/config.yaml (if exists) + environment variables."""
    config_path = _PROJECT_ROOT / "config" / "config.yaml"
    yaml_data: dict = {}

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}

    # Database URL: prefer database_url (PostgreSQL), fallback to database_path (SQLite)
    db_url = yaml_data.get("storage", {}).get("database_url", "")
    if not db_url:
        db_path = yaml_data.get("storage", {}).get(
            "database_path", "data/stockagent.db"
        )
        abs_db_path = (_PROJECT_ROOT / db_path).resolve()
        abs_db_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{abs_db_path}"

    # TuShare token (yaml → env override)
    ts_token = (
        yaml_data.get("data_sources", {}).get("tushare", {}).get("token", "")
    )
    ts_token = os.environ.get("TUSHARE_TOKEN", ts_token)

    ds_yaml = yaml_data.get("data_sources", {})

    # DeepSeek config (yaml → env override)
    ds_cfg = yaml_data.get("deepseek", {})
    deepseek_api_key = os.environ.get(
        "DEEPSEEK_API_KEY", ds_cfg.get("api_key", "")
    )

    # Qwen local config
    qwen_cfg = yaml_data.get("qwen", {})

    # AI Lab scoring weights
    ai_lab_yaml = yaml_data.get("ai_lab", {})

    # Auth config
    auth_yaml = yaml_data.get("auth", {})

    return Settings(
        ai_lab=AILabConfig(
            weight_return=ai_lab_yaml.get("weight_return", 0.30),
            weight_drawdown=ai_lab_yaml.get("weight_drawdown", 0.25),
            weight_sharpe=ai_lab_yaml.get("weight_sharpe", 0.25),
            weight_plr=ai_lab_yaml.get("weight_plr", 0.20),
        ),
        deepseek=DeepSeekConfig(
            api_key=deepseek_api_key,
            base_url=ds_cfg.get("base_url", "https://api.deepseek.com/v1"),
            model=ds_cfg.get("model", "deepseek-chat"),
        ),
        qwen=QwenConfig(
            api_key=qwen_cfg.get("api_key", "not-needed"),
            base_url=qwen_cfg.get("base_url", "http://192.168.100.172:8680/v1"),
            model=qwen_cfg.get("model", "qwen3.5-35b-a3b"),
        ),
        data_sources=DataSourceConfig(
            tushare_token=ts_token,
            fallback_enabled=ds_yaml.get("fallback_enabled", True),
            request_interval=ds_yaml.get("request_interval", 0.3),
            realtime_quotes=ds_yaml.get("realtime_quotes", "tdx"),
            historical_daily=ds_yaml.get("historical_daily", "tdx"),
            index_data=ds_yaml.get("index_data", "tdx"),
            sector_data=ds_yaml.get("sector_data", "tdx"),
            money_flow=ds_yaml.get("money_flow", "tushare"),
            stock_list=ds_yaml.get("stock_list", "tdx"),
            daily_batch=ds_yaml.get("daily_batch", "tushare"),
            fundamentals=ds_yaml.get("fundamentals", "tushare"),
            trade_calendar=ds_yaml.get("trade_calendar", "tushare"),
            tushare_rate_limit=ds_yaml.get("tushare", {}).get("rate_limit", 190),
        ),
        auth=AuthConfig(
            enabled=auth_yaml.get("enabled", True),
            bypass_local=auth_yaml.get("bypass_local", True),
        ),
        database=DatabaseConfig(url=db_url),
        debug=os.environ.get("DEBUG", "").lower() in ("1", "true"),
    )
