"""Stock-related Pydantic schemas."""

from typing import Optional
from pydantic import BaseModel


class StockInfo(BaseModel):
    code: str
    name: str
    market: str = ""
    industry: str = ""


class StockListResponse(BaseModel):
    total: int
    items: list[StockInfo]


class WatchlistItem(BaseModel):
    stock_code: str
    stock_name: str = ""
    sort_order: int = 0
    close: Optional[float] = None
    change_pct: Optional[float] = None
    date: Optional[str] = None


class WatchlistAddRequest(BaseModel):
    stock_code: str
    stock_name: Optional[str] = ""


class PortfolioItem(BaseModel):
    stock_code: str
    stock_name: str = ""
    quantity: int = 0
    avg_cost: float = 0.0
    close: Optional[float] = None
    change_pct: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    market_value: Optional[float] = None


class PortfolioAddRequest(BaseModel):
    stock_code: str
    stock_name: Optional[str] = ""
    quantity: int
    avg_cost: float
