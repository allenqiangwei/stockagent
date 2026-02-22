"""Market regime ORM model — weekly regime labels from Shanghai Index."""

import datetime

from sqlalchemy import Date, String, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MarketRegimeLabel(Base):
    """Weekly market regime label derived from Shanghai Composite Index (000001).

    Each row represents one natural week (Mon-Fri) with the detected regime
    and supporting indicators.
    """

    __tablename__ = "market_regimes"

    week_start: Mapped[datetime.date] = mapped_column(Date, primary_key=True)  # Monday
    week_end: Mapped[datetime.date] = mapped_column(Date)                       # Friday
    regime: Mapped[str] = mapped_column(String(20))              # trending_bull/bear/ranging/volatile
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    trend_strength: Mapped[float] = mapped_column(Float, default=0.0)
    volatility: Mapped[float] = mapped_column(Float, default=0.0)
    breadth: Mapped[float] = mapped_column(Float, default=0.5)
    index_return_pct: Mapped[float] = mapped_column(Float, default=0.0)  # Weekly index return %
