"""Beta factor ORM models — snapshots, reviews, and aggregated insights."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Float, Text, DateTime, Index
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BetaSnapshot(Base):
    """Point-in-time snapshot of non-technical factors at AI decision time."""
    __tablename__ = "beta_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), index=True)
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)
    report_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trade_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Market context (from market_regimes + news_sentiment_results)
    market_regime: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    market_regime_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_sentiment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentiment_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Stock / industry / sector (from stocks + stock_concepts + sector_heat)
    industry: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    concepts: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    stock_sentiment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sector_heat_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sector_trend: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Valuation (from daily_basic)
    pe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Active news events (from news_events)
    active_events: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # AI decision
    action: Mapped[str] = mapped_column(String(10), default="")
    alpha_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_reasoning: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_beta_snap_code_date", "stock_code", "snapshot_date"),
        Index("ix_beta_snap_report", "report_id"),
    )


class BetaReview(Base):
    """Post-mortem evaluation of beta factors for a completed trade."""
    __tablename__ = "beta_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(Integer, index=True)
    stock_code: Mapped[str] = mapped_column(String(6), index=True)

    pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    holding_days: Mapped[int] = mapped_column(Integer, default=0)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Factor accuracy scores: -1=misleading, 0=neutral, +1=predictive
    regime_accuracy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sentiment_accuracy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sector_heat_accuracy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    news_event_accuracy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    valuation_accuracy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Structured details from AI evaluation
    factor_details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    key_lesson: Mapped[str] = mapped_column(String(500), default="")
    entry_snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class BetaInsight(Base):
    """Aggregated beta knowledge derived from multiple trade reviews."""
    __tablename__ = "beta_insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    insight_type: Mapped[str] = mapped_column(String(30), index=True)
    dimension: Mapped[str] = mapped_column(String(100))

    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_factor_accuracy: Mapped[float] = mapped_column(Float, default=0.0)

    insight_text: Mapped[str] = mapped_column(Text, default="")
    source_review_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_beta_insight_type_dim", "insight_type", "dimension"),
    )
