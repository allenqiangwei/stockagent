"""Beta factor Pydantic schemas."""

from pydantic import BaseModel
from typing import Optional


class BetaSnapshotItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    snapshot_date: str
    report_id: Optional[int] = None
    market_regime: Optional[str] = None
    market_sentiment: Optional[float] = None
    industry: Optional[str] = None
    concepts: Optional[list] = None
    sector_heat_score: Optional[float] = None
    sector_trend: Optional[str] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    action: str = ""
    alpha_score: Optional[float] = None
    ai_reasoning: str = ""


class BetaReviewItem(BaseModel):
    id: int
    review_id: int
    stock_code: str
    pnl_pct: float
    holding_days: int
    exit_reason: Optional[str] = None
    regime_accuracy: Optional[int] = None
    sentiment_accuracy: Optional[int] = None
    sector_heat_accuracy: Optional[int] = None
    news_event_accuracy: Optional[int] = None
    valuation_accuracy: Optional[int] = None
    key_lesson: str = ""
    factor_details: Optional[dict] = None


class BetaInsightItem(BaseModel):
    insight_type: str
    dimension: str
    sample_count: int
    avg_pnl_pct: float
    win_rate: float
    avg_factor_accuracy: float
    insight_text: str
