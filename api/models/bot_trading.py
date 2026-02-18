"""Bot Trading ORM models — simulated portfolio, trades, and reviews."""

from datetime import datetime

from sqlalchemy import Integer, String, Float, DateTime, Text, Index, Boolean
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BotPortfolio(Base):
    """Robot simulated portfolio — separate from user's real portfolio."""

    __tablename__ = "bot_portfolio"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_invested: Mapped[float] = mapped_column(Float, default=0.0)
    first_buy_date: Mapped[str] = mapped_column(String(10), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class BotTrade(Base):
    """Individual trade record with thinking process."""

    __tablename__ = "bot_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), index=True)
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    action: Mapped[str] = mapped_column(String(10))  # buy|sell|reduce|hold
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    thinking: Mapped[str] = mapped_column(Text, default="")
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_bot_trade_code_date", "stock_code", "trade_date"),
    )


class BotTradeReview(Base):
    """Post-mortem review after fully exiting a position."""

    __tablename__ = "bot_trade_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), index=True)
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    total_buy_amount: Mapped[float] = mapped_column(Float, default=0.0)
    total_sell_amount: Mapped[float] = mapped_column(Float, default=0.0)
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    first_buy_date: Mapped[str] = mapped_column(String(10), default="")
    last_sell_date: Mapped[str] = mapped_column(String(10), default="")
    holding_days: Mapped[int] = mapped_column(Integer, default=0)
    review_thinking: Mapped[str] = mapped_column(Text, default="")
    memory_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_note_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trades: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
