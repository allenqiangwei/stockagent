"""Gamma Factor ORM model — 缠论 snapshot per stock per day."""

from datetime import datetime

from sqlalchemy import String, Float, Integer, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GammaSnapshot(Base):
    __tablename__ = "gamma_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6))
    snapshot_date: Mapped[str] = mapped_column(String(10))

    # Gamma scoring dimensions
    gamma_score: Mapped[float] = mapped_column(Float, default=0.0)
    daily_strength: Mapped[float] = mapped_column(Float, default=0.0)
    weekly_resonance: Mapped[float] = mapped_column(Float, default=0.0)
    structure_health: Mapped[float] = mapped_column(Float, default=0.0)

    # Raw 缠论 signal data (for ML features)
    daily_mmd_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    daily_mmd_level: Mapped[str | None] = mapped_column(String(5), nullable=True)
    daily_mmd_age: Mapped[int] = mapped_column(Integer, default=0)
    weekly_mmd_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    weekly_mmd_level: Mapped[str | None] = mapped_column(String(5), nullable=True)
    daily_bc_count: Mapped[int] = mapped_column(Integer, default=0)
    daily_bi_zs_count: Mapped[int] = mapped_column(Integer, default=0)
    daily_last_bi_dir: Mapped[str | None] = mapped_column(String(5), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_gamma_snap_code_date", "stock_code", "snapshot_date", unique=True),
    )
