"""Job and JobEvent models — unified task tracking."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, DateTime, Text, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(
        String(30), index=True,
        comment="experiment|backtest|ai_analysis|ai_chat|data_sync|news_agent|trade_review|beta_aggregation",
    )
    status: Mapped[str] = mapped_column(
        String(20), index=True, default="queued",
        comment="queued|running|succeeded|failed|canceled",
    )
    title: Mapped[str] = mapped_column(String(200), comment="Human-readable title")
    ref_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="experiment|backtest_run|ai_report",
    )
    ref_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="api_key_name|system|scheduler",
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, comment="Monotonic sequence within job")
    event_type: Mapped[str] = mapped_column(
        String(20), comment="progress|log|error|metric|artifact",
    )
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
