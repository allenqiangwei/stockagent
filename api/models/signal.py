"""TradingSignal and ActionSignal ORM models."""

from datetime import datetime

from sqlalchemy import String, Float, Integer, DateTime, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TradingSignal(Base):
    __tablename__ = "trading_signals_v2"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6))
    trade_date: Mapped[str] = mapped_column(String(10))
    final_score: Mapped[float] = mapped_column(Float)
    signal_level: Mapped[int] = mapped_column(Integer)
    signal_level_name: Mapped[str] = mapped_column(String(20), default="")
    swing_score: Mapped[float] = mapped_column(Float, nullable=True)
    trend_score: Mapped[float] = mapped_column(Float, nullable=True)
    market_regime: Mapped[str] = mapped_column(String(20), nullable=True)
    reasons: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_signal_v2_code_date"),
        Index("ix_signal_v2_date", "trade_date"),
        Index("ix_signal_v2_stock", "stock_code", "trade_date"),
    )


class ActionSignal(Base):
    __tablename__ = "action_signals_v2"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6))
    trade_date: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(4))  # BUY / SELL
    strategy_name: Mapped[str] = mapped_column(String(100))
    confidence_score: Mapped[float] = mapped_column(Float, nullable=True)
    sell_reason: Mapped[str] = mapped_column(String(20), nullable=True)
    trigger_rules: Mapped[str] = mapped_column(Text, default="[]")
    reasons: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "stock_code", "trade_date", "action", "strategy_name",
            name="uq_action_v2_unique",
        ),
        Index("ix_action_v2_date", "trade_date", "action"),
    )
