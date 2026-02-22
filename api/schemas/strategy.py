"""Strategy-related Pydantic schemas."""

from typing import Optional, Literal
from pydantic import BaseModel, field_validator


class ExitConfigSchema(BaseModel):
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    max_hold_days: Optional[int] = None


class ComboConfig(BaseModel):
    """Configuration for a combo (ensemble) strategy that votes across members."""
    type: Literal["combo"] = "combo"
    member_ids: list[int]           # IDs of member strategies
    vote_threshold: int = 2         # min votes for buy signal (equal mode)
    weight_mode: Literal["equal", "score_weighted"] = "equal"
    score_threshold: float = 2.0    # weighted score threshold (score_weighted mode)
    sell_mode: Literal["any", "majority"] = "any"  # sell trigger mode

    @field_validator("member_ids")
    @classmethod
    def at_least_two_members(cls, v):
        if len(v) < 2:
            raise ValueError("组合策略至少需要2个成员策略")
        return v

    @field_validator("vote_threshold")
    @classmethod
    def threshold_positive(cls, v):
        if v < 1:
            raise ValueError("投票门槛至少为1")
        return v


class ComboCreate(BaseModel):
    """Create a combo strategy."""
    name: str
    description: str = ""
    combo_config: ComboConfig
    exit_config: ExitConfigSchema = ExitConfigSchema(
        stop_loss_pct=-8, take_profit_pct=20, max_hold_days=20,
    )


class StrategyCreate(BaseModel):
    name: str
    description: str = ""
    rules: list[dict] = []
    buy_conditions: list[dict] = []
    sell_conditions: list[dict] = []
    exit_config: ExitConfigSchema = ExitConfigSchema()
    weight: float = 0.5
    enabled: bool = True
    rank_config: Optional[dict] = None
    portfolio_config: Optional[dict] = None
    category: Optional[str] = None


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rules: Optional[list[dict]] = None
    buy_conditions: Optional[list[dict]] = None
    sell_conditions: Optional[list[dict]] = None
    exit_config: Optional[ExitConfigSchema] = None
    weight: Optional[float] = None
    enabled: Optional[bool] = None
    rank_config: Optional[dict] = None
    portfolio_config: Optional[dict] = None
    category: Optional[str] = None


class StrategyClone(BaseModel):
    """Override fields when cloning a strategy."""
    name: str
    description: Optional[str] = None
    exit_config: Optional[ExitConfigSchema] = None
    buy_conditions: Optional[list[dict]] = None
    sell_conditions: Optional[list[dict]] = None
    portfolio_config: Optional[dict] = None


class StrategyResponse(BaseModel):
    id: int
    name: str
    description: str
    rules: list[dict]
    buy_conditions: list[dict]
    sell_conditions: list[dict]
    exit_config: dict
    weight: float
    enabled: bool
    rank_config: Optional[dict] = None
    portfolio_config: Optional[dict] = None
    category: Optional[str] = None
    backtest_summary: Optional[dict] = None
    source_experiment_id: Optional[int] = None

    model_config = {"from_attributes": True}
