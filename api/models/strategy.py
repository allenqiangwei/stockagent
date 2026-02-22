"""Strategy ORM model — stores rules, buy/sell conditions, exit config as JSON."""

from datetime import datetime

from sqlalchemy import String, Float, Integer, Boolean, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    rules: Mapped[dict] = mapped_column(JSON, default=list)
    buy_conditions: Mapped[dict] = mapped_column(JSON, default=list)
    sell_conditions: Mapped[dict] = mapped_column(JSON, default=list)
    exit_config: Mapped[dict] = mapped_column(JSON, default=dict)
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rank_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    portfolio_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    category: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    backtest_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    source_experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
