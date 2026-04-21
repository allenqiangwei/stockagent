"""Pydantic schemas for Ops Overview."""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel

from api.schemas.job import JobSummary


class OpsOverview(BaseModel):
    # Service
    uptime_seconds: float
    version: str
    database_ok: bool

    # Schedulers
    data_sync: dict
    news_agent: dict

    # Jobs
    running_jobs: list[JobSummary]
    recent_failed_jobs: list[JobSummary]
    job_counts_24h: dict  # {succeeded: N, failed: N, canceled: N}

    # Data freshness
    latest_daily_price_date: Optional[str] = None
    latest_ai_report_date: Optional[str] = None
    latest_news_event_time: Optional[str] = None

    # Strategy library
    total_strategies: int = 0
    total_experiments: int = 0
    total_exploration_rounds: int = 0

    # Bot
    bot_portfolio_count: int = 0
    pending_trade_plans: int = 0

    # Errors
    recent_errors: list[dict] = []
