"""Strategies CRUD router."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.strategy import Strategy
from api.models.backtest import BacktestRun
from api.schemas.strategy import (
    StrategyCreate, StrategyUpdate, StrategyClone, StrategyResponse,
    ComboCreate,
)
from src.signals.rule_engine import INDICATOR_GROUPS, OPERATORS

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("/indicator-groups")
def get_indicator_groups():
    """Return indicator metadata for the frontend rule editor."""
    return {"groups": INDICATOR_GROUPS, "operators": OPERATORS}


@router.get("", response_model=list[StrategyResponse])
def list_strategies(
    category: str = Query("", description="Filter: 全能/牛市/熊市/震荡 or _manual for uncategorized"),
    db: Session = Depends(get_db),
):
    """List all strategies, optionally filtered by category."""
    q = db.query(Strategy)
    if category == "_manual":
        q = q.filter(Strategy.category.is_(None))
    elif category:
        q = q.filter(Strategy.category == category)
    rows = q.order_by(Strategy.id).all()
    return [StrategyResponse.model_validate(r) for r in rows]


@router.get("/{strategy_id}", response_model=StrategyResponse)
def get_strategy(strategy_id: int, db: Session = Depends(get_db)):
    """Get a single strategy by ID."""
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not s:
        raise HTTPException(404, "Strategy not found")
    return StrategyResponse.model_validate(s)


@router.post("", response_model=StrategyResponse, status_code=201)
def create_strategy(req: StrategyCreate, db: Session = Depends(get_db)):
    """Create a new strategy."""
    existing = db.query(Strategy).filter(Strategy.name == req.name).first()
    if existing:
        raise HTTPException(409, f"Strategy '{req.name}' already exists")

    s = Strategy(
        name=req.name,
        description=req.description,
        rules=req.rules,
        buy_conditions=req.buy_conditions,
        sell_conditions=req.sell_conditions,
        exit_config=req.exit_config.model_dump(),
        weight=req.weight,
        enabled=req.enabled,
        rank_config=req.rank_config,
        portfolio_config=req.portfolio_config,
        category=req.category,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return StrategyResponse.model_validate(s)


@router.put("/{strategy_id}", response_model=StrategyResponse)
def update_strategy(
    strategy_id: int,
    req: StrategyUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing strategy."""
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not s:
        raise HTTPException(404, "Strategy not found")

    update_data = req.model_dump(exclude_unset=True)
    if "exit_config" in update_data and update_data["exit_config"] is not None:
        update_data["exit_config"] = update_data["exit_config"].model_dump() if hasattr(update_data["exit_config"], "model_dump") else dict(update_data["exit_config"])

    for key, val in update_data.items():
        setattr(s, key, val)

    db.commit()
    db.refresh(s)
    return StrategyResponse.model_validate(s)


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: int, db: Session = Depends(get_db)):
    """Delete a strategy. Unlinks (but preserves) any associated backtest runs."""
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not s:
        raise HTTPException(404, "Strategy not found")
    # Unlink backtest runs so they aren't orphaned (preserves history)
    db.query(BacktestRun).filter(BacktestRun.strategy_id == strategy_id).update(
        {"strategy_id": None}
    )
    db.delete(s)
    db.commit()
    return {"deleted": strategy_id}


@router.post("/cleanup")
def cleanup_strategies(
    min_score: float = Query(0.70, description="Minimum score to keep"),
    min_return_pct: float = Query(20.0, description="Minimum return % to keep"),
    max_drawdown_pct: float = Query(25.0, description="Maximum drawdown % to keep"),
    min_trades: int = Query(50, description="Minimum trades to keep"),
    dry_run: bool = Query(False, description="If true, only count without deleting"),
    db: Session = Depends(get_db),
):
    """Delete promoted strategies below quality threshold and reset lab flags."""
    from api.models.ai_lab import ExperimentStrategy

    # Find strategies to delete: those with backtest_summary below threshold
    all_strats = db.query(Strategy).all()
    to_delete = []
    for s in all_strats:
        bs = s.backtest_summary or {}
        score = bs.get("score", 0) or 0
        ret = bs.get("total_return_pct", 0) or 0
        dd = abs(bs.get("max_drawdown_pct", 0) or 0)
        trades = bs.get("total_trades", 0) or 0
        # Keep if meets ALL criteria; delete if fails ANY
        if score < min_score or ret <= min_return_pct or dd >= max_drawdown_pct or trades < min_trades:
            to_delete.append(s)

    if dry_run:
        return {
            "dry_run": True,
            "would_delete": len(to_delete),
            "would_keep": len(all_strats) - len(to_delete),
        }

    # Delete and reset lab flags
    deleted_ids = []
    for s in to_delete:
        # Unlink backtest runs
        db.query(BacktestRun).filter(BacktestRun.strategy_id == s.id).update(
            {"strategy_id": None}
        )
        # Reset lab experiment strategy promoted flags
        db.query(ExperimentStrategy).filter(
            ExperimentStrategy.promoted_strategy_id == s.id
        ).update({"promoted": False, "promoted_strategy_id": None})
        deleted_ids.append(s.id)
        db.delete(s)

    db.commit()
    return {
        "deleted": len(deleted_ids),
        "kept": len(all_strats) - len(deleted_ids),
    }


@router.post("/combo", response_model=StrategyResponse, status_code=201)
def create_combo_strategy(req: ComboCreate, db: Session = Depends(get_db)):
    """Create a combo (ensemble) strategy that votes across member strategies."""
    # Validate: all member strategies exist and are enabled
    members = (
        db.query(Strategy)
        .filter(Strategy.id.in_(req.combo_config.member_ids))
        .all()
    )
    found_ids = {m.id for m in members}
    missing = set(req.combo_config.member_ids) - found_ids
    if missing:
        raise HTTPException(404, f"成员策略不存在: {sorted(missing)}")

    disabled = [m.name for m in members if not m.enabled]
    if disabled:
        raise HTTPException(400, f"成员策略未启用: {disabled}")

    # vote_threshold must not exceed member count
    if req.combo_config.vote_threshold > len(req.combo_config.member_ids):
        raise HTTPException(
            400,
            f"投票门槛({req.combo_config.vote_threshold})不能超过成员数({len(req.combo_config.member_ids)})",
        )

    existing = db.query(Strategy).filter(Strategy.name == req.name).first()
    if existing:
        raise HTTPException(409, f"Strategy '{req.name}' already exists")

    s = Strategy(
        name=req.name,
        description=req.description,
        rules=[],
        buy_conditions=[],   # combo strategies have no direct conditions
        sell_conditions=[],
        exit_config=req.exit_config.model_dump(),
        weight=0.5,
        enabled=True,
        category="combo",
        portfolio_config=req.combo_config.model_dump(),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return StrategyResponse.model_validate(s)


@router.post("/{strategy_id}/clone", response_model=StrategyResponse, status_code=201)
def clone_strategy(strategy_id: int, req: StrategyClone, db: Session = Depends(get_db)):
    """Clone a strategy with optional overrides (e.g. different stop-loss)."""
    src = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not src:
        raise HTTPException(404, "Source strategy not found")
    existing = db.query(Strategy).filter(Strategy.name == req.name).first()
    if existing:
        raise HTTPException(409, f"Strategy '{req.name}' already exists")

    import copy
    clone = Strategy(
        name=req.name,
        description=req.description if req.description is not None else src.description,
        rules=copy.deepcopy(src.rules),
        buy_conditions=req.buy_conditions if req.buy_conditions is not None else copy.deepcopy(src.buy_conditions),
        sell_conditions=req.sell_conditions if req.sell_conditions is not None else copy.deepcopy(src.sell_conditions),
        exit_config=req.exit_config.model_dump() if req.exit_config is not None else copy.deepcopy(src.exit_config),
        weight=src.weight,
        enabled=True,
        rank_config=copy.deepcopy(src.rank_config),
        portfolio_config=req.portfolio_config if req.portfolio_config is not None else copy.deepcopy(src.portfolio_config),
        category=src.category,
        source_experiment_id=src.source_experiment_id,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return StrategyResponse.model_validate(clone)
