"""Bot Trading Pydantic schemas."""

from typing import Optional
from pydantic import BaseModel


class BotPortfolioItem(BaseModel):
    id: Optional[int] = None
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
    # Exit monitoring
    strategy_id: Optional[int] = None
    strategy_name: Optional[str] = None
    exit_config: Optional[dict] = None
    buy_price: Optional[float] = None
    buy_date: Optional[str] = None
    # Derived fields (computed at query time)
    hold_days: Optional[int] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    days_remaining: Optional[int] = None


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
    sell_reason: Optional[str] = None

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


class BotTradePlanItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str = ""
    direction: str  # "buy" | "sell"
    plan_price: float = 0.0
    quantity: int = 0
    sell_pct: float = 0.0
    plan_date: str = ""
    status: str = "pending"
    thinking: str = ""
    report_id: Optional[int] = None
    source: str = "ai"  # ai|beta|stop_loss|take_profit|max_hold
    strategy_id: Optional[int] = None
    created_at: str = ""
    executed_at: Optional[str] = None
    execution_price: Optional[float] = None
    # Beta scoring
    alpha_score: Optional[float] = None
    beta_score: Optional[float] = None
    combined_score: Optional[float] = None
    gamma_score: Optional[float] = None
    gamma_daily_strength: Optional[float] = None
    gamma_weekly_resonance: Optional[float] = None
    gamma_structure_health: Optional[float] = None
    gamma_daily_mmd: Optional[str] = None  # e.g. "3B:笔"
    gamma_weekly_mmd: Optional[str] = None
    phase: Optional[str] = None  # cold|warm|mature
    # Signal quality grade
    signal_grade: Optional[str] = None  # green|yellow|red
    signal_win_rate: Optional[float] = None
    confidence: Optional[float] = None
    # Strategy details (enriched from strategy lookup)
    strategy_name: Optional[str] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    max_hold_days: Optional[int] = None
    buy_conditions: Optional[list] = None
    sell_conditions: Optional[list] = None
    # Today's market data (populated if available)
    today_close: Optional[float] = None
    today_change_pct: Optional[float] = None
    today_high: Optional[float] = None
    today_low: Optional[float] = None

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
    sl_count: int = 0
    tp_count: int = 0
    mhd_count: int = 0
    ai_sell_count: int = 0


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


# ── Trading Diary schemas ──

class DiaryRefreshStep(BaseModel):
    name: str
    status: str  # done|running|pending|failed|skipped
    duration_sec: Optional[float] = None
    detail: str = ""
    progress: Optional[str] = None
    error: Optional[str] = None

class DiaryRefresh(BaseModel):
    job_id: Optional[int] = None
    status: str  # succeeded|running|failed|not_started
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_sec: Optional[float] = None
    steps: list[DiaryRefreshStep] = []
    error: Optional[str] = None

class DiaryExecutionBuy(BaseModel):
    code: str
    name: str
    price: float
    quantity: int
    amount: float
    plan_price: float = 0
    day_low: Optional[float] = None
    trigger: str = ""
    strategy_name: Optional[str] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    gamma: Optional[float] = None
    combined: Optional[float] = None

class DiaryExecutionSell(BaseModel):
    code: str
    name: str
    price: float
    quantity: int
    amount: float
    reason: str
    reason_label: str
    buy_price: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    hold_days: Optional[int] = None
    trigger: str = ""

class DiaryExecutionExpired(BaseModel):
    code: str
    name: str
    direction: str
    plan_price: float
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    reason: str
    source: Optional[str] = None

class DiaryExecutionSummary(BaseModel):
    plans_total: int = 0
    executed: int = 0
    expired: int = 0
    buys: int = 0
    sells_tp: int = 0
    sells_sl: int = 0
    sells_mhd: int = 0
    sells_ai: int = 0
    sells_signal: int = 0

class DiaryExecution(BaseModel):
    summary: DiaryExecutionSummary
    buy_list: list[DiaryExecutionBuy] = []
    sell_list: list[DiaryExecutionSell] = []
    expired_list: list[DiaryExecutionExpired] = []

class DiaryPlanBuy(BaseModel):
    code: str
    name: str
    plan_price: Optional[float] = None
    quantity: Optional[int] = None
    strategy_name: Optional[str] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    gamma: Optional[float] = None
    combined: Optional[float] = None
    gamma_daily_mmd: Optional[str] = None
    gamma_weekly_mmd: Optional[str] = None
    source: str = "beta"
    reason: str = ""

class DiaryPlanSell(BaseModel):
    code: str
    name: str
    plan_price: Optional[float] = None
    source: str
    source_label: str
    reason: str = ""
    hold_days: Optional[int] = None
    strategy_name: Optional[str] = None

class DiaryPlansSummary(BaseModel):
    buy: int = 0
    sell_tp: int = 0
    sell_sl: int = 0
    sell_mhd: int = 0
    sell_signal: int = 0

class DiaryPlansCreated(BaseModel):
    for_date: str = ""
    summary: DiaryPlansSummary = DiaryPlansSummary()
    buy_list: list[DiaryPlanBuy] = []
    sell_list: list[DiaryPlanSell] = []

class DiarySignals(BaseModel):
    generated: int = 0
    buy_signals: int = 0
    sell_signals: int = 0

class DiaryPortfolioSnapshot(BaseModel):
    total_holdings: int = 0
    total_invested: float = 0
    total_market_value: Optional[float] = None
    daily_pnl: Optional[float] = None
    daily_pnl_pct: Optional[float] = None

class TradingDiary(BaseModel):
    date: str
    is_trading_day: bool = True
    refresh: DiaryRefresh
    execution: DiaryExecution
    portfolio_snapshot: Optional[DiaryPortfolioSnapshot] = None
    signals: DiarySignals
    plans_created: DiaryPlansCreated
