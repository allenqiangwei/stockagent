"""Backtest ORM models — run history and trade details."""

from datetime import datetime

from sqlalchemy import (
    String, Float, Integer, DateTime, Text, JSON, ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs_v2"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("strategies.id"), nullable=True, index=True
    )
    strategy_name: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[str] = mapped_column(String(10))
    end_date: Mapped[str] = mapped_column(String(10))
    capital_per_trade: Mapped[float] = mapped_column(Float, default=10000.0)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    total_return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    avg_hold_days: Mapped[float] = mapped_column(Float, default=0.0)
    avg_pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    result_json: Mapped[str] = mapped_column(Text, nullable=True)
    # Portfolio mode columns (nullable for backwards compat)
    backtest_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    initial_capital: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_positions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cagr_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    calmar_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_loss_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Market regime analysis
    regime_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    index_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    trades: Mapped[list["BacktestTrade"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class BacktestTrade(Base):
    __tablename__ = "backtest_trades_v2"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("backtest_runs_v2.id"), index=True
    )
    stock_code: Mapped[str] = mapped_column(String(6))
    strategy_name: Mapped[str] = mapped_column(String(100), default="")
    buy_date: Mapped[str] = mapped_column(String(10), nullable=True)
    buy_price: Mapped[float] = mapped_column(Float, nullable=True)
    sell_date: Mapped[str] = mapped_column(String(10), nullable=True)
    sell_price: Mapped[float] = mapped_column(Float, nullable=True)
    sell_reason: Mapped[str] = mapped_column(String(20), nullable=True)
    pnl_pct: Mapped[float] = mapped_column(Float, nullable=True)
    hold_days: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped["BacktestRun"] = relationship(back_populates="trades")

    __table_args__ = (
        Index("ix_bt_trades_run", "run_id"),
    )
