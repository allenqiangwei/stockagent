"""AI Lab Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ── Templates ─────────────────────────────────────

class TemplateCreate(BaseModel):
    name: str
    category: str = "组合"
    description: str = ""


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None


class TemplateResponse(BaseModel):
    id: int
    name: str
    category: str
    description: str
    is_builtin: bool

    model_config = {"from_attributes": True}


# ── Experiments ───────────────────────────────────

class ExperimentCreate(BaseModel):
    theme: str
    source_type: str = "template"  # "template" | "custom"
    source_text: str = ""
    initial_capital: float = 100000.0
    max_positions: int = 10
    max_position_pct: float = 30.0


class ExperimentStrategyResponse(BaseModel):
    id: int
    experiment_id: int
    name: str
    description: str
    buy_conditions: list[dict]
    sell_conditions: list[dict]
    exit_config: dict
    status: str
    error_message: str
    total_trades: int
    win_rate: float
    total_return_pct: float
    max_drawdown_pct: float
    avg_hold_days: float
    avg_pnl_pct: float
    score: float
    backtest_run_id: Optional[int]
    promoted: bool
    promoted_strategy_id: Optional[int]

    model_config = {"from_attributes": True}


class ExperimentResponse(BaseModel):
    id: int
    theme: str
    source_type: str
    source_text: str
    status: str
    strategy_count: int
    created_at: str
    strategies: list[ExperimentStrategyResponse] = []

    model_config = {"from_attributes": True}


class ExperimentListItem(BaseModel):
    id: int
    theme: str
    source_type: str
    status: str
    strategy_count: int
    best_score: float = 0.0
    best_name: str = ""
    created_at: str

    model_config = {"from_attributes": True}


# ── Combo Experiment ──────────────────────────────

class ComboExperimentCreate(BaseModel):
    """Create a combo experiment that tests signal voting across member strategies."""
    theme: str = "组合策略投票"
    member_strategy_ids: list[int]  # promoted Strategy IDs to combine
    vote_thresholds: list[int] = []  # auto-generate if empty (e.g. [2, 3, 4] for 5 members)
    sell_mode: str = "any"  # "any" | "majority"
    exit_config: Optional[dict] = None  # override exit config for all variants
    initial_capital: float = 100000.0
    max_positions: int = 10
    max_position_pct: float = 30.0


# ── Clone & Backtest ─────────────────────────────

class CloneBacktestRequest(BaseModel):
    """Clone an existing experiment strategy with modified exit params and re-backtest."""
    source_strategy_id: int
    name_suffix: str = ""
    exit_config: Optional[dict] = None  # Override: stop_loss_pct, take_profit_pct, max_hold_days
    initial_capital: float = 100000.0
    max_positions: int = 10
    max_position_pct: float = 30.0


# ── Exploration Rounds ───────────────────────────

class ExplorationRoundCreate(BaseModel):
    round_number: int
    mode: str = "semi-auto"
    started_at: str
    finished_at: str
    experiment_ids: list[int] = []
    total_experiments: int = 0
    total_strategies: int = 0
    profitable_count: int = 0
    profitability_pct: float = 0.0
    std_a_count: int = 0
    best_strategy_name: str = ""
    best_strategy_score: float = 0.0
    best_strategy_return: float = 0.0
    best_strategy_dd: float = 0.0
    insights: list[str] = []
    promoted: list[dict] = []
    issues_resolved: list[str] = []
    next_suggestions: list[str] = []
    summary: str = ""
    memory_synced: bool = False
    pinecone_synced: bool = False


class ExplorationRoundResponse(BaseModel):
    id: int
    round_number: int
    mode: str
    started_at: datetime
    finished_at: datetime
    experiment_ids: list[int]
    total_experiments: int
    total_strategies: int
    profitable_count: int
    profitability_pct: float
    std_a_count: int
    best_strategy_name: str
    best_strategy_score: float
    best_strategy_return: float
    best_strategy_dd: float
    insights: list[str]
    promoted: list[dict]
    issues_resolved: list[str]
    next_suggestions: list[str]
    summary: str
    memory_synced: bool
    pinecone_synced: bool

    model_config = {"from_attributes": True}
