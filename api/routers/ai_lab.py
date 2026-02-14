"""AI Lab router — experiments, templates, strategy promotion."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.ai_lab import StrategyTemplate, Experiment, ExperimentStrategy
from api.schemas.ai_lab import (
    TemplateCreate, TemplateUpdate, TemplateResponse,
    ExperimentCreate, ExperimentResponse, ExperimentListItem,
)

router = APIRouter(prefix="/api/lab", tags=["ai-lab"])


# ── Templates ─────────────────────────────────────

@router.get("/templates", response_model=list[TemplateResponse])
def list_templates(
    category: str = Query("", description="Filter by category"),
    db: Session = Depends(get_db),
):
    q = db.query(StrategyTemplate)
    if category:
        q = q.filter(StrategyTemplate.category == category)
    return q.order_by(StrategyTemplate.category, StrategyTemplate.id).all()


@router.post("/templates", response_model=TemplateResponse)
def create_template(data: TemplateCreate, db: Session = Depends(get_db)):
    tpl = StrategyTemplate(
        name=data.name,
        category=data.category,
        description=data.description,
        is_builtin=False,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.put("/templates/{template_id}", response_model=TemplateResponse)
def update_template(
    template_id: int, data: TemplateUpdate, db: Session = Depends(get_db),
):
    tpl = db.query(StrategyTemplate).get(template_id)
    if not tpl:
        raise HTTPException(404, "Template not found")
    if data.name is not None:
        tpl.name = data.name
    if data.category is not None:
        tpl.category = data.category
    if data.description is not None:
        tpl.description = data.description
    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    tpl = db.query(StrategyTemplate).get(template_id)
    if not tpl:
        raise HTTPException(404, "Template not found")
    db.delete(tpl)
    db.commit()
    return {"deleted": template_id}


# ── Experiments ───────────────────────────────────

@router.get("/experiments")
def list_experiments(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    total = db.query(Experiment).count()
    rows = (
        db.query(Experiment)
        .order_by(Experiment.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    items = []
    for exp in rows:
        best = (
            db.query(ExperimentStrategy)
            .filter(
                ExperimentStrategy.experiment_id == exp.id,
                ExperimentStrategy.status == "done",
            )
            .order_by(ExperimentStrategy.score.desc())
            .first()
        )
        items.append({
            "id": exp.id,
            "theme": exp.theme,
            "source_type": exp.source_type,
            "status": exp.status,
            "strategy_count": exp.strategy_count,
            "best_score": best.score if best else 0.0,
            "best_name": best.name if best else "",
            "created_at": exp.created_at.strftime("%Y-%m-%d %H:%M") if exp.created_at else "",
        })
    return {"total": total, "items": items}


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: int, db: Session = Depends(get_db)):
    exp = db.query(Experiment).get(experiment_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")

    from api.models.strategy import Strategy

    strategies = (
        db.query(ExperimentStrategy)
        .filter(ExperimentStrategy.experiment_id == exp.id)
        .order_by(ExperimentStrategy.score.desc())
        .all()
    )

    # Check which promoted strategies still exist (user may have deleted them)
    promoted_ids = [s.promoted_strategy_id for s in strategies if s.promoted and s.promoted_strategy_id]
    existing_ids = set()
    if promoted_ids:
        rows = db.query(Strategy.id).filter(Strategy.id.in_(promoted_ids)).all()
        existing_ids = {r.id for r in rows}

    return {
        "id": exp.id,
        "theme": exp.theme,
        "source_type": exp.source_type,
        "source_text": exp.source_text,
        "status": exp.status,
        "strategy_count": exp.strategy_count,
        "created_at": exp.created_at.strftime("%Y-%m-%d %H:%M") if exp.created_at else "",
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "buy_conditions": s.buy_conditions,
                "sell_conditions": s.sell_conditions,
                "exit_config": s.exit_config,
                "status": s.status,
                "error_message": s.error_message,
                "total_trades": s.total_trades,
                "win_rate": s.win_rate,
                "total_return_pct": s.total_return_pct,
                "max_drawdown_pct": s.max_drawdown_pct,
                "avg_hold_days": s.avg_hold_days,
                "avg_pnl_pct": s.avg_pnl_pct,
                "score": s.score,
                "backtest_run_id": s.backtest_run_id,
                "regime_stats": s.regime_stats,
                "promoted": s.promoted and s.promoted_strategy_id in existing_ids,
                "promoted_strategy_id": s.promoted_strategy_id if s.promoted_strategy_id in existing_ids else None,
            }
            for s in strategies
        ],
    }


@router.delete("/experiments/{experiment_id}")
def delete_experiment(experiment_id: int, db: Session = Depends(get_db)):
    """Delete an experiment and all related data (strategies + backtest runs)."""
    from api.models.backtest import BacktestRun, BacktestTrade
    from api.services.ai_lab_engine import get_runner

    exp = db.query(Experiment).get(experiment_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")

    # Refuse to delete while the experiment is still running
    if exp.status in ("pending", "generating", "backtesting") or get_runner().is_running(experiment_id):
        raise HTTPException(409, "实验正在运行中，请等待完成后再删除")

    # Clean up associated backtest runs (not FK-linked, must delete manually)
    strats = (
        db.query(ExperimentStrategy)
        .filter(ExperimentStrategy.experiment_id == experiment_id)
        .all()
    )
    run_ids = [s.backtest_run_id for s in strats if s.backtest_run_id]
    if run_ids:
        db.query(BacktestTrade).filter(BacktestTrade.run_id.in_(run_ids)).delete(
            synchronize_session=False
        )
        db.query(BacktestRun).filter(BacktestRun.id.in_(run_ids)).delete(
            synchronize_session=False
        )

    # Delete experiment (cascades to experiment_strategies)
    db.delete(exp)
    db.commit()
    return {"deleted": experiment_id}


@router.post("/experiments")
def create_experiment(
    data: ExperimentCreate, db: Session = Depends(get_db),
):
    """Create experiment and start background execution. Returns SSE stream."""
    from api.services.ai_lab_engine import get_runner

    exp = Experiment(
        theme=data.theme,
        source_type=data.source_type,
        source_text=data.source_text,
        initial_capital=data.initial_capital,
        max_positions=data.max_positions,
        max_position_pct=data.max_position_pct,
        status="pending",
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)

    runner = get_runner()
    progress = runner.start(exp.id)

    return StreamingResponse(
        progress.iter_from(0),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/experiments/{experiment_id}/stream")
def experiment_stream(experiment_id: int, db: Session = Depends(get_db)):
    """Reconnect to a running experiment's SSE stream."""
    from api.services.ai_lab_engine import get_runner

    runner = get_runner()
    progress = runner.get_progress(experiment_id)

    if progress is not None:
        # Experiment still running (or recently finished) — stream from beginning
        return StreamingResponse(
            progress.iter_from(0),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # No active progress — check DB for final state
    exp = db.query(Experiment).get(experiment_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")

    def _status_stream():
        yield f"data: {json.dumps({'type': 'experiment_status', 'status': exp.status}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _status_stream(),
        media_type="text/event-stream",
    )


# ── Promote strategy ─────────────────────────────

@router.post("/strategies/{strategy_id}/promote")
def promote_strategy(
    strategy_id: int,
    label: str = Query("[AI]", description="Name prefix label, e.g. [AI], [AI-牛市], [AI-震荡]"),
    db: Session = Depends(get_db),
):
    """Copy an experiment strategy to the formal strategy library."""
    from api.models.strategy import Strategy

    exp_strat = db.query(ExperimentStrategy).get(strategy_id)
    if not exp_strat:
        raise HTTPException(404, "Experiment strategy not found")

    if exp_strat.promoted and exp_strat.promoted_strategy_id:
        # Check if the formal strategy still exists (user may have deleted it)
        existing = db.query(Strategy).filter(
            Strategy.id == exp_strat.promoted_strategy_id
        ).first()
        if existing:
            return {"message": "Already promoted", "strategy_id": exp_strat.promoted_strategy_id}
        # Formal strategy was deleted — allow re-promotion

    formal = Strategy(
        name=f"{label} {exp_strat.name}",
        description=exp_strat.description,
        rules=[],
        buy_conditions=exp_strat.buy_conditions,
        sell_conditions=exp_strat.sell_conditions,
        exit_config=exp_strat.exit_config,
        weight=0.5,
        enabled=False,  # user enables manually
    )
    db.add(formal)
    db.flush()

    exp_strat.promoted = True
    exp_strat.promoted_strategy_id = formal.id
    db.commit()

    return {"message": "Promoted", "strategy_id": formal.id}


# ── Market Regimes ───────────────────────────────

@router.get("/regimes")
def get_regimes(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """Query market regime labels and summary for a date range."""
    from api.services.regime_service import ensure_regimes, get_regime_summary
    from api.models.market_regime import MarketRegimeLabel

    ensure_regimes(db, start_date, end_date)
    summary = get_regime_summary(db, start_date, end_date)

    # Also return weekly detail
    from datetime import date, timedelta

    def _monday_of(d):
        return d - timedelta(days=d.weekday())

    def _friday_of(d):
        return d + timedelta(days=4 - d.weekday())

    rows = (
        db.query(MarketRegimeLabel)
        .filter(
            MarketRegimeLabel.week_start >= _monday_of(date.fromisoformat(start_date)),
            MarketRegimeLabel.week_end <= _friday_of(date.fromisoformat(end_date)),
        )
        .order_by(MarketRegimeLabel.week_start)
        .all()
    )

    weeks = [
        {
            "week_start": r.week_start.isoformat() if hasattr(r.week_start, "isoformat") else str(r.week_start),
            "week_end": r.week_end.isoformat() if hasattr(r.week_end, "isoformat") else str(r.week_end),
            "regime": r.regime,
            "confidence": r.confidence,
            "trend_strength": r.trend_strength,
            "volatility": r.volatility,
            "index_return_pct": r.index_return_pct,
        }
        for r in rows
    ]

    return {**summary, "weeks": weeks}
