"""News sentiment analysis models."""

from datetime import datetime, timedelta

from sqlalchemy import Column, Integer, Float, String, Text, DateTime, Boolean, Index
from sqlalchemy.types import JSON

from api.models.base import Base


class NewsSentimentResult(Base):
    """Market-level sentiment analysis result from DeepSeek."""

    __tablename__ = "news_sentiment_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_time = Column(DateTime, default=datetime.now, nullable=False)
    period_type = Column(String(20), nullable=False)  # "pre_market" / "post_close" / "manual"
    news_count = Column(Integer, default=0)
    market_sentiment = Column(Float, default=0.0)  # -100 ~ +100
    confidence = Column(Float, default=0.0)  # 0 ~ 100
    event_tags = Column(JSON, default=list)
    key_summary = Column(Text, default="")
    stock_mentions = Column(JSON, default=list)
    sector_impacts = Column(JSON, default=list)
    raw_response = Column(Text, default="")

    __table_args__ = (
        Index("idx_sentiment_time", "analysis_time"),
        Index("idx_sentiment_period", "period_type", "analysis_time"),
    )


class StockNewsSentiment(Base):
    """Per-stock sentiment analysis result (on-demand)."""

    __tablename__ = "stock_news_sentiment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False)
    stock_name = Column(String(50), default="")
    analysis_time = Column(DateTime, default=datetime.now, nullable=False)
    sentiment = Column(Float, default=0.0)  # -100 ~ +100
    news_count = Column(Integer, default=0)
    summary = Column(Text, default="")
    valid_until = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_stock_sentiment_code", "stock_code", "analysis_time"),
    )

    @property
    def is_valid(self) -> bool:
        return datetime.now() < self.valid_until
