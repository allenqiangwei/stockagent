"""Stock, DailyPrice, StockConcept, and BoardSyncLog ORM models."""

from datetime import date, datetime

from sqlalchemy import (
    Integer, String, Float, Date, DateTime, Index, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50))
    market: Mapped[str] = mapped_column(String(4), default="")   # SH / SZ
    industry: Mapped[str] = mapped_column(String(50), default="")
    list_date: Mapped[str] = mapped_column(String(10), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class DailyPrice(Base):
    __tablename__ = "daily_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), index=True)
    trade_date: Mapped[date] = mapped_column(Date)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    amount: Mapped[float] = mapped_column(Float, default=0)

    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_daily_code_date"),
        Index("ix_daily_code_date", "stock_code", "trade_date"),
    )


class StockConcept(Base):
    """Many-to-many: one stock can belong to multiple concept boards."""
    __tablename__ = "stock_concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), index=True)
    concept_name: Mapped[str] = mapped_column(String(50))

    __table_args__ = (
        UniqueConstraint("stock_code", "concept_name", name="uq_stock_concept"),
        Index("ix_concept_code", "stock_code"),
    )


class BoardSyncLog(Base):
    """Track last sync time per board type to enforce daily limit."""
    __tablename__ = "board_sync_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_type: Mapped[str] = mapped_column(String(20), unique=True)  # "industry" | "concept"
    last_synced: Mapped[datetime] = mapped_column(DateTime)
    record_count: Mapped[int] = mapped_column(default=0)


class DailyBasic(Base):
    """Per-stock per-date fundamental data (PE/PB/market cap) from TuShare daily_basic."""
    __tablename__ = "daily_basic"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), index=True)
    trade_date: Mapped[date] = mapped_column(Date)
    pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_mv: Mapped[float | None] = mapped_column(Float, nullable=True)
    circ_mv: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_basic_code_date"),
        Index("ix_basic_code_date", "stock_code", "trade_date"),
    )


class TradingCalendar(Base):
    """SSE/SZSE trading calendar — cached from TuShare trade_cal API."""
    __tablename__ = "trading_calendar"

    id: Mapped[int] = mapped_column(primary_key=True)
    exchange: Mapped[str] = mapped_column(String(6), default="SSE")
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    is_open: Mapped[int] = mapped_column(Integer, default=1)  # 0=closed, 1=open

    __table_args__ = (
        UniqueConstraint("exchange", "trade_date", name="uq_cal_exchange_date"),
    )


INDEX_CODES = {
    "000001.SH": {"name": "上证指数", "ak_symbol": "sh000001"},
    "399001.SZ": {"name": "深证成指", "ak_symbol": "sz399001"},
    "399006.SZ": {"name": "创业板指", "ak_symbol": "sz399006"},
}


class IndexDaily(Base):
    """Daily OHLCV data for major indices (上证/深成指/创业板)."""
    __tablename__ = "index_daily"

    id: Mapped[int] = mapped_column(primary_key=True)
    index_code: Mapped[str] = mapped_column(String(10))   # "000001.SH"
    trade_date: Mapped[date] = mapped_column(Date)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)

    __table_args__ = (
        UniqueConstraint("index_code", "trade_date", name="uq_index_code_date"),
        Index("ix_index_code_date", "index_code", "trade_date"),
    )


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    stock_name: Mapped[str] = mapped_column(String(50), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
