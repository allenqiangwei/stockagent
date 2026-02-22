"""Signal-related Pydantic schemas."""

from typing import Optional
from pydantic import BaseModel


class SignalItem(BaseModel):
    stock_code: str
    trade_date: str
    final_score: float
    signal_level: int
    signal_level_name: str = ""
    swing_score: Optional[float] = None
    trend_score: Optional[float] = None
    market_regime: Optional[str] = None
    reasons: list[str] = []


class SignalListResponse(BaseModel):
    trade_date: str
    total: int
    items: list[SignalItem]


class SignalGenerateRequest(BaseModel):
    stock_codes: Optional[list[str]] = None  # None = all tracked stocks
