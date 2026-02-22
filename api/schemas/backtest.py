"""Backtest-related Pydantic schemas."""

from typing import Optional
from pydantic import BaseModel


class BacktestRunRequest(BaseModel):
    strategy_id: int
    start_date: str       # YYYY-MM-DD
    end_date: str         # YYYY-MM-DD
    capital_per_trade: float = 10000.0
    stock_codes: list[str] = []
    scope: str = "sample"  # "sample" | "all" | "custom"


class TradeDetail(BaseModel):
    stock_code: str
    strategy_name: str = ""
    buy_date: Optional[str] = None
    buy_price: Optional[float] = None
    sell_date: Optional[str] = None
    sell_price: Optional[float] = None
    sell_reason: Optional[str] = None
    pnl_pct: Optional[float] = None
    hold_days: int = 0


class EquityPoint(BaseModel):
    date: str
    equity: float


class BacktestResultResponse(BaseModel):
    id: Optional[int] = None
    strategy_name: str
    start_date: str
    end_date: str
    capital_per_trade: float
    total_trades: int
    win_trades: int
    lose_trades: int
    win_rate: float
    total_return_pct: float
    max_drawdown_pct: float
    avg_hold_days: float
    avg_pnl_pct: float
    equity_curve: list[EquityPoint] = []
    sell_reason_stats: dict = {}
    trades: list[TradeDetail] = []
    # Portfolio mode fields
    backtest_mode: Optional[str] = None
    initial_capital: Optional[float] = None
    max_positions: Optional[int] = None
    cagr_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None
    profit_loss_ratio: Optional[float] = None


class BacktestRunSummary(BaseModel):
    id: int
    strategy_name: str
    start_date: str
    end_date: str
    total_trades: int
    win_rate: float
    total_return_pct: float
    max_drawdown_pct: float
    created_at: str
    # Portfolio mode fields
    backtest_mode: Optional[str] = None
    cagr_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None

    model_config = {"from_attributes": True}
