"""News agent pipeline ORM models: events, sector heat, news signals, run log."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer, String, Float, Text, DateTime, Index, UniqueConstraint, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NewsEvent(Base):
    """Structured event extracted from news articles."""
    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(30))
    impact_level: Mapped[str] = mapped_column(String(10))
    impact_direction: Mapped[str] = mapped_column(String(10))
    affected_codes: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    affected_sectors: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text)
    source_titles: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    analysis_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_news_events_type", "event_type", "created_at"),
        Index("idx_news_events_date", "created_at"),
    )


class SectorHeat(Base):
    """Sector heat snapshot from news analysis."""
    __tablename__ = "sector_heat"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime)
    sector_name: Mapped[str] = mapped_column(String(50))
    sector_type: Mapped[str] = mapped_column(String(10))
    heat_score: Mapped[float] = mapped_column(Float)
    news_count: Mapped[int] = mapped_column(Integer, default=0)
    trend: Mapped[str] = mapped_column(String(10), default="flat")
    top_stocks: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    event_summary: Mapped[str] = mapped_column(Text, default="")
    analysis_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_sector_heat_time", "snapshot_time"),
        Index("idx_sector_heat_name", "sector_name", "snapshot_time"),
    )


class NewsSignal(Base):
    """News-driven trading signal."""
    __tablename__ = "news_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(10))
    stock_code: Mapped[str] = mapped_column(String(6))
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    action: Mapped[str] = mapped_column(String(5))
    signal_source: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text)
    related_event_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    sector_name: Mapped[str] = mapped_column(String(50), default="")
    analysis_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_news_signals_date", "trade_date"),
        Index("idx_news_signals_code", "stock_code", "trade_date"),
        UniqueConstraint("trade_date", "stock_code", "signal_source", name="uq_news_signal"),
    )


class AgentRunLog(Base):
    """Execution log for each agent run."""
    __tablename__ = "agent_run_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_time: Mapped[datetime] = mapped_column(DateTime)
    period_type: Mapped[str] = mapped_column(String(15))
    agent_name: Mapped[str] = mapped_column(String(30))
    input_news_count: Mapped[int] = mapped_column(Integer, default=0)
    output_summary: Mapped[str] = mapped_column(Text, default="")
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="completed")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
