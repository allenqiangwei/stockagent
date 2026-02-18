"""Bot Trading Pydantic schemas."""

from typing import Optional
from pydantic import BaseModel


class BotPortfolioItem(BaseModel):
    stock_code: str
    stock_name: str = ""
    quantity: int = 0
    avg_cost: float = 0.0
    total_invested: float = 0.0
    first_buy_date: str = ""
    # Computed at query time
    close: Optional[float] = None
    change_pct: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    market_value: Optional[float] = None


class BotTradeItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str = ""
    action: str
    quantity: int = 0
    price: float = 0.0
    amount: float = 0.0
    thinking: str = ""
    report_id: Optional[int] = None
    trade_date: str = ""
    created_at: str = ""

    model_config = {"from_attributes": True}


class BotTradeReviewItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str = ""
    total_buy_amount: float = 0.0
    total_sell_amount: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    first_buy_date: str = ""
    last_sell_date: str = ""
    holding_days: int = 0
    review_thinking: str = ""
    memory_synced: bool = False
    memory_note_id: Optional[str] = None
    trades: Optional[list] = None
    created_at: str = ""

    model_config = {"from_attributes": True}


class BotSummary(BaseModel):
    total_invested: float = 0.0
    current_market_value: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    active_positions: int = 0
    completed_trades: int = 0
    reviews_count: int = 0
    win_count: int = 0
    loss_count: int = 0


class BotStockTimeline(BaseModel):
    """Full timeline for a single stock: all trades + optional review."""
    stock_code: str
    stock_name: str = ""
    status: str = ""  # "holding" | "closed"
    total_buy_amount: float = 0.0
    total_sell_amount: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    first_buy_date: str = ""
    last_trade_date: str = ""
    holding_days: int = 0
    current_quantity: int = 0
    current_price: Optional[float] = None
    current_market_value: Optional[float] = None
    trades: list[BotTradeItem] = []
    review: Optional[BotTradeReviewItem] = None
