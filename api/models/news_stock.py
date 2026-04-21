"""News-to-stock association and price alignment models.

Proposal A: Link individual news articles to specific stocks.
Stores per-stock forward returns for backtesting news predictive power.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Float, Text, DateTime, Date, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NewsStockLink(Base):
    """Maps a news article to a specific stock with relevance scoring.

    Sources of matching:
      - code_mention: stock code appears in title/content
      - name_mention: stock name appears in title/content
      - concept_match: article keywords match stock concepts
      - event_affected: NewsAgent event lists this stock in affected_codes
    """
    __tablename__ = "news_stock_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[int] = mapped_column(Integer, nullable=False)  # FK to news_archive.id
    stock_code: Mapped[str] = mapped_column(String(6), nullable=False)
    match_type: Mapped[str] = mapped_column(String(20), nullable=False)  # code_mention / name_mention / concept_match / event_affected
    relevance_score: Mapped[float] = mapped_column(Float, default=1.0)  # 0~1, higher = more relevant
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("news_id", "stock_code", name="uq_news_stock_link"),
        Index("idx_nsl_stock", "stock_code", "created_at"),
        Index("idx_nsl_news", "news_id"),
    )


class NewsPriceAligned(Base):
    """News aligned to trading day with forward returns.

    Enables backtesting: "when this news appeared, what happened to the stock?"
    """
    __tablename__ = "news_price_aligned"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_code: Mapped[str] = mapped_column(String(6), nullable=False)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    publish_time: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    sentiment: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # positive/negative/neutral
    ret_t0: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # same-day return
    ret_t1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # T+1 return
    ret_t3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ret_t5: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("news_id", "stock_code", name="uq_news_price_aligned"),
        Index("idx_npa_stock_date", "stock_code", "trade_date"),
        Index("idx_npa_date", "trade_date"),
    )
