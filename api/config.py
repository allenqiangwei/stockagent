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
    # Per-category data source preference: "tushare" | "akshare"
    realtime_quotes: str = "tushare"
    historical_daily: str = "tushare"
    index_data: str = "tushare"
    sector_data: str = "tushare"
    money_flow: str = "tushare"
    stock_list: str = "tushare"
    tushare_rate_limit: int = 190


class DatabaseConfig(BaseModel):
    url: str = ""


class DeepSeekConfig(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"


class AILabConfig(BaseModel):
    """Scoring weights for AI Lab experiments (must sum to 1.0)."""
    weight_return: float = 0.30
    weight_drawdown: float = 0.25
    weight_sharpe: float = 0.25
    weight_plr: float = 0.20


class Settings(BaseModel):
    project_root: Path = _PROJECT_ROOT
    data_sources: DataSourceConfig = DataSourceConfig()
    database: DatabaseConfig = DatabaseConfig()
    deepseek: DeepSeekConfig = DeepSeekConfig()
    ai_lab: AILabConfig = AILabConfig()
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    """Load settings from config/config.yaml (if exists) + environment variables."""
    config_path = _PROJECT_ROOT / "config" / "config.yaml"
    yaml_data: dict = {}

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}

    # Database path
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

    # AI Lab scoring weights
    ai_lab_yaml = yaml_data.get("ai_lab", {})

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
        data_sources=DataSourceConfig(
            tushare_token=ts_token,
            fallback_enabled=ds_yaml.get("fallback_enabled", True),
            request_interval=ds_yaml.get("request_interval", 0.3),
            realtime_quotes=ds_yaml.get("realtime_quotes", "tushare"),
            historical_daily=ds_yaml.get("historical_daily", "tushare"),
            index_data=ds_yaml.get("index_data", "tushare"),
            sector_data=ds_yaml.get("sector_data", "tushare"),
            money_flow=ds_yaml.get("money_flow", "tushare"),
            stock_list=ds_yaml.get("stock_list", "tushare"),
            tushare_rate_limit=ds_yaml.get("tushare", {}).get("rate_limit", 190),
        ),
        database=DatabaseConfig(url=db_url),
        debug=os.environ.get("DEBUG", "").lower() in ("1", "true"),
    )
