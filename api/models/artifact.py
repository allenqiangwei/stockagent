"""Artifact model — metadata pointers for reproducibility tracking."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, Text, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_type: Mapped[str] = mapped_column(
        String(30), index=True,
        comment="backtest_result|ai_report|experiment_result|strategy",
    )
    uri: Mapped[str] = mapped_column(
        String(500), comment="e.g. db://backtest_runs_v2/42"
    )
    content_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="SHA-256 of content"
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True,
    )
    producer: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="Module that created this"
    )
    code_version: Mapped[Optional[str]] = mapped_column(
        String(12), nullable=True, comment="git short hash"
    )
    data_version: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, comment="Latest daily price date"
    )
    config_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="SHA-256 of config snapshot"
    )
    config_snapshot: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="Frozen config at creation time"
    )
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSON, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True,
    )
