"""Market-related Pydantic schemas for API request/response."""

from typing import Optional
from pydantic import BaseModel


class KlineBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndicatorPoint(BaseModel):
    date: str
    values: dict[str, Optional[float]]


class KlineResponse(BaseModel):
    stock_code: str
    stock_name: str
    period: str
    bars: list[KlineBar]
    signals: list[dict] = []  # [{date, action, strategy_name}]


class IndicatorResponse(BaseModel):
    stock_code: str
    indicators: list[str]
    data: list[IndicatorPoint]


class QuoteResponse(BaseModel):
    stock_code: str
    stock_name: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    change_pct: Optional[float] = None


class RegimeWeek(BaseModel):
    week_start: str
    week_end: str
    regime: str
    confidence: float
    trend_strength: float
    volatility: float
    index_return_pct: float


class IndexKlineResponse(BaseModel):
    index_code: str
    index_name: str
    period: str
    bars: list[KlineBar]
    regimes: list[RegimeWeek]
