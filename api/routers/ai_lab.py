"""AI Lab router — experiments, templates, strategy promotion."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.ai_lab import StrategyTemplate, Experiment, ExperimentStrategy, ExplorationRound
from api.schemas.ai_lab import (
    TemplateCreate, TemplateUpdate, TemplateResponse,
    ExperimentCreate, ExperimentResponse, ExperimentListItem,
    CloneBacktestRequest, ComboExperimentCreate,
    ExplorationRoundCreate, ExplorationRoundResponse,
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

_LABEL_CATEGORY_MAP = {
    "[AI]": "全能",
    "[AI-牛市]": "牛市",
    "[AI-熊市]": "熊市",
    "[AI-震荡]": "震荡",
}


@router.post("/strategies/{strategy_id}/promote")
def promote_strategy(
    strategy_id: int,
    label: str = Query("[AI]", description="Name prefix label, e.g. [AI], [AI-牛市], [AI-震荡]"),
    category: str = Query("", description="Category override (全能/牛市/熊市/震荡). Inferred from label if empty."),
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

    # Infer category from label if not explicitly provided
    resolved_category = category if category else _LABEL_CATEGORY_MAP.get(label)

    # Build backtest summary from experiment strategy metrics
    backtest_summary = {
        "score": exp_strat.score,
        "total_return_pct": exp_strat.total_return_pct,
        "max_drawdown_pct": exp_strat.max_drawdown_pct,
        "win_rate": exp_strat.win_rate,
        "total_trades": exp_strat.total_trades,
        "avg_hold_days": exp_strat.avg_hold_days,
        "avg_pnl_pct": exp_strat.avg_pnl_pct,
        "regime_stats": exp_strat.regime_stats,
    }

    # Build unique name — append exit params suffix for clone variants
    base_name = f"{label} {exp_strat.name}"
    existing = db.query(Strategy).filter(Strategy.name == base_name).first()
    if existing:
        ec = exp_strat.exit_config or {}
        sl = abs(ec.get("stop_loss_pct", 0))
        tp = ec.get("take_profit_pct", 0)
        base_name = f"{base_name}_SL{sl:.0f}_TP{tp:.0f}"
        # Still duplicate? Add strategy ID
        if db.query(Strategy).filter(Strategy.name == base_name).first():
            base_name = f"{base_name}_v{exp_strat.id}"

    formal = Strategy(
        name=base_name,
        description=exp_strat.description,
        rules=[],
        buy_conditions=exp_strat.buy_conditions,
        sell_conditions=exp_strat.sell_conditions,
        exit_config=exp_strat.exit_config,
        weight=0.5,
        enabled=False,  # user enables manually
        category=resolved_category,
        backtest_summary=backtest_summary,
        source_experiment_id=exp_strat.id,
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


# ── Clone & Backtest ──────────────────────────────

@router.post("/strategies/{strategy_id}/clone-backtest")
def clone_and_backtest(
    strategy_id: int,
    req: CloneBacktestRequest,
    db: Session = Depends(get_db),
):
    """Clone an experiment strategy with modified exit params, then run a full
    lab-style portfolio backtest using the same stock pool and scoring.

    This bypasses DeepSeek entirely — useful for parameter optimization of
    proven strategies (e.g. adjusting stop-loss/take-profit on top strategies).
    """
    import copy
    import threading
    from datetime import datetime, timedelta

    source = db.query(ExperimentStrategy).get(strategy_id)
    if not source:
        raise HTTPException(404, "Source experiment strategy not found")
    if source.status != "done":
        raise HTTPException(400, f"Source strategy status is '{source.status}', must be 'done'")

    # Create a "clone" experiment to hold the new strategy
    suffix = req.name_suffix or "调参"
    exp = Experiment(
        theme=f"[克隆调参] {source.name}_{suffix}",
        source_type="clone",
        source_text=f"克隆自 ExperimentStrategy ID{source.id} ({source.name}), 修改 exit_config",
        status="backtesting",
        strategy_count=1,
    )
    db.add(exp)
    db.flush()

    # Build merged exit config
    exit_config = copy.deepcopy(source.exit_config or {})
    if req.exit_config:
        exit_config.update(req.exit_config)

    # Normalize: stop_loss_pct must be negative (e.g. -8 for 8% stop loss)
    if "stop_loss_pct" in exit_config and exit_config["stop_loss_pct"] is not None:
        exit_config["stop_loss_pct"] = -abs(exit_config["stop_loss_pct"])

    # Create the cloned strategy
    cloned = ExperimentStrategy(
        experiment_id=exp.id,
        name=f"{source.name}_{suffix}",
        description=f"克隆自 {source.name}, exit_config={json.dumps(exit_config)}",
        buy_conditions=copy.deepcopy(source.buy_conditions),
        sell_conditions=copy.deepcopy(source.sell_conditions),
        exit_config=exit_config,
        status="pending",
    )
    db.add(cloned)
    db.commit()

    # Run backtest in background thread
    clone_id = cloned.id
    exp_id = exp.id

    def _run_backtest():
        from api.models.base import SessionLocal
        from api.services.ai_lab_engine import AILabEngine, _BACKTEST_SEMAPHORE

        # Acquire semaphore BEFORE data loading to prevent concurrent SQLite thrashing
        _BACKTEST_SEMAPHORE.acquire()
        session = SessionLocal()
        try:
            engine = AILabEngine(session)
            strat = session.query(ExperimentStrategy).get(clone_id)
            experiment = session.query(Experiment).get(exp_id)

            # Use same data pipeline as lab
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")

            stock_codes = engine.collector.get_stocks_with_data(min_rows=60)
            stock_data = {}
            for code in stock_codes:
                df = engine.collector.get_daily_df(code, start_date, end_date, local_only=True)
                if df is not None and not df.empty and len(df) >= 60:
                    stock_data[code] = df

            if not stock_data:
                strat.status = "failed"
                strat.error_message = "No stock data available"
                experiment.status = "failed"
                session.commit()
                return

            # Get regime map
            from api.services.regime_service import ensure_regimes, get_regime_map, get_regime_summary
            ensure_regimes(session, start_date, end_date)
            regime_map = get_regime_map(session, start_date, end_date)
            summary = get_regime_summary(session, start_date, end_date)
            index_return_pct = summary.get("total_index_return_pct", 0.0)

            # Run the backtest — _run_single_backtest also acquires semaphore internally,
            # but since we already hold it and Semaphore is reentrant-safe for same thread,
            # call the impl directly to avoid deadlock.
            engine._run_single_backtest_impl(
                strat, stock_data, start_date, end_date,
                experiment, regime_map, index_return_pct,
            )
            experiment.status = "done"
            session.commit()
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                strat = session.query(ExperimentStrategy).get(clone_id)
                exp_obj = session.query(Experiment).get(exp_id)
                if strat:
                    strat.status = "failed"
                    strat.error_message = str(e)[:500]
                if exp_obj:
                    exp_obj.status = "failed"
                session.commit()
            except Exception:
                session.rollback()
        finally:
            _BACKTEST_SEMAPHORE.release()
            session.close()

    threading.Thread(target=_run_backtest, daemon=True).start()

    return {
        "message": "Clone created and backtest started",
        "experiment_id": exp.id,
        "strategy_id": cloned.id,
        "name": cloned.name,
        "exit_config": exit_config,
    }


# ── Retry / Resume Backtests ─────────────────────

@router.post("/experiments/{experiment_id}/retry")
def retry_experiment(
    experiment_id: int,
    db: Session = Depends(get_db),
):
    """Resume backtesting for pending strategies in an experiment.

    This picks up where a crashed/stuck backtest left off — only processes
    strategies with status 'pending', 'backtesting', or 'failed' (if they
    have buy_conditions). Already 'done' and 'invalid' strategies are skipped.
    """
    from api.services.ai_lab_engine import get_runner

    exp = db.query(Experiment).get(experiment_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")

    # Count retryable strategies
    strategies = (
        db.query(ExperimentStrategy)
        .filter(ExperimentStrategy.experiment_id == experiment_id)
        .all()
    )
    retryable = [
        s for s in strategies
        if s.status in ("pending", "backtesting")
        or (s.status == "failed" and s.buy_conditions)
    ]

    if not retryable:
        return {"message": "No retryable strategies", "experiment_id": experiment_id}

    runner = get_runner()
    if runner.is_running(experiment_id):
        return {"message": "Experiment already running", "experiment_id": experiment_id}

    progress = runner.resume(experiment_id)

    return StreamingResponse(
        progress.iter_from(0),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/experiments/retry-pending")
def retry_all_pending(db: Session = Depends(get_db)):
    """Find all experiments stuck in backtesting with pending strategies and
    queue them for retry. Returns list of experiment IDs that were queued.

    This endpoint launches retries sequentially to avoid overloading the system.
    """
    from api.services.ai_lab_engine import get_runner
    import threading

    # Find experiments with pending strategies (any non-done/non-generating status)
    stuck_exps = (
        db.query(Experiment)
        .filter(Experiment.status.in_(["backtesting", "pending", "failed"]))
        .all()
    )

    queued = []
    runner = get_runner()

    for exp in stuck_exps:
        if runner.is_running(exp.id):
            continue

        pending = (
            db.query(ExperimentStrategy)
            .filter(
                ExperimentStrategy.experiment_id == exp.id,
                ExperimentStrategy.status.in_(["pending", "backtesting"]),
            )
            .count()
        )
        if pending > 0:
            queued.append({"id": exp.id, "theme": exp.theme, "pending_count": pending})

    if not queued:
        return {"message": "No experiments need retry", "queued": []}

    # Launch retries sequentially in a background thread
    exp_ids = [q["id"] for q in queued]

    def _retry_all():
        from api.models.base import SessionLocal
        from api.services.ai_lab_engine import AILabEngine, ExperimentProgress

        for eid in exp_ids:
            session = SessionLocal()
            try:
                engine = AILabEngine(session)
                progress = ExperimentProgress()
                engine.resume_backtests(eid, progress)
            except Exception as e:
                logger.error("Retry experiment %d failed: %s", eid, e)
                try:
                    exp_obj = session.query(Experiment).get(eid)
                    if exp_obj and exp_obj.status not in ("done", "failed"):
                        exp_obj.status = "failed"
                    session.commit()
                except Exception:
                    session.rollback()
            finally:
                session.close()

    import logging
    logger = logging.getLogger(__name__)
    threading.Thread(target=_retry_all, daemon=True, name="retry-all-pending").start()

    return {
        "message": f"Queued {len(queued)} experiments for retry",
        "queued": queued,
    }


# ── Combo Experiments ─────────────────────────────

@router.post("/experiments/combo")
def create_combo_experiment(
    body: Optional[ComboExperimentCreate] = None,
    db: Session = Depends(get_db),
):
    """Create a combo experiment from promoted [AI] strategies.

    If body.member_strategy_ids is provided, uses those specific strategies.
    Otherwise loads all promoted AI strategies.
    """
    from api.models.strategy import Strategy
    from api.services.ai_lab_engine import get_runner

    # Load member strategies — either specified or all promoted
    if body and body.member_strategy_ids:
        promoted = (
            db.query(Strategy)
            .filter(Strategy.id.in_(body.member_strategy_ids))
            .all()
        )
        if len(promoted) < 2:
            raise HTTPException(400, f"至少需要2个有效策略, 找到{len(promoted)}个")
    else:
        promoted = (
            db.query(Strategy)
            .filter(
                Strategy.enabled.is_(True),
                Strategy.source_experiment_id.isnot(None),
                Strategy.category.in_(["全能", "combo"]),
            )
            .all()
        )
        if len(promoted) < 2:
            raise HTTPException(400, f"至少需要2个promoted策略, 当前仅{len(promoted)}个")

    member_ids = [s.id for s in promoted]
    member_names = [s.name for s in promoted]
    n = len(member_ids)

    sell_mode = body.sell_mode if body else "any"
    exit_cfg = body.exit_config if body and body.exit_config else {"stop_loss_pct": -8, "take_profit_pct": 20, "max_hold_days": 20}
    initial_capital = body.initial_capital if body else 100000.0
    max_positions = body.max_positions if body else 10
    max_position_pct = body.max_position_pct if body else 30.0
    theme = body.theme if body else f"组合策略投票({n}成员)"

    # Generate vote threshold variants
    if body and body.vote_thresholds:
        thresholds = [t for t in body.vote_thresholds if 2 <= t <= n]
    else:
        thresholds = list(range(2, n + 1))

    # Create experiment
    exp = Experiment(
        theme=theme,
        source_type="combo",
        source_text=f"成员策略: {', '.join(member_names[:5])}{'...' if len(member_names) > 5 else ''}",
        initial_capital=initial_capital,
        max_positions=max_positions,
        max_position_pct=max_position_pct,
        status="pending",
    )
    db.add(exp)
    db.flush()

    # Create one ExperimentStrategy per threshold variant
    for threshold in thresholds:
        combo_config = {
            "type": "combo",
            "member_ids": member_ids,
            "vote_threshold": threshold,
            "weight_mode": "equal",
            "sell_mode": "any",
        }
        strat = ExperimentStrategy(
            experiment_id=exp.id,
            name=f"投票{threshold}/{n}",
            description=f"至少{threshold}个策略同意才买入, {n}个成员",
            buy_conditions=[],
            sell_conditions=[],
            exit_config=exit_cfg,
            status="pending",
        )
        strat.regime_stats = combo_config
        db.add(strat)

    # Also add "majority" sell mode variant for mid threshold
    mid_threshold = max(2, n // 2)
    combo_config = {
        "type": "combo",
        "member_ids": member_ids,
        "vote_threshold": mid_threshold,
        "weight_mode": "equal",
        "sell_mode": "majority",
    }
    strat = ExperimentStrategy(
        experiment_id=exp.id,
        name=f"投票{mid_threshold}/{n}_多数卖出",
        description=f"买入需{mid_threshold}/{n}同意, 卖出需多数成员同意",
        buy_conditions=[],
        sell_conditions=[],
        exit_config=exit_cfg,
        status="pending",
    )
    strat.regime_stats = combo_config
    db.add(strat)

    exp.strategy_count = len(thresholds) + 1
    db.commit()

    # Start the experiment (uses resume path since strategies are pre-created)
    runner = get_runner()
    progress = runner.resume(exp.id)

    return StreamingResponse(
        progress.iter_from(0),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Exploration Rounds ────────────────────────────

@router.get("/exploration-rounds")
def list_exploration_rounds(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    total = db.query(ExplorationRound).count()
    items = (
        db.query(ExplorationRound)
        .order_by(ExplorationRound.finished_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return {
        "items": [ExplorationRoundResponse.model_validate(r) for r in items],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/exploration-rounds/{round_id}", response_model=ExplorationRoundResponse)
def get_exploration_round(round_id: int, db: Session = Depends(get_db)):
    row = db.query(ExplorationRound).filter(ExplorationRound.id == round_id).first()
    if not row:
        raise HTTPException(404, "Exploration round not found")
    return row


@router.put("/exploration-rounds/{round_id}", response_model=ExplorationRoundResponse)
def update_exploration_round(round_id: int, data: ExplorationRoundCreate, db: Session = Depends(get_db)):
    """Update an existing exploration round record."""
    from datetime import datetime as dt
    row = db.query(ExplorationRound).filter(ExplorationRound.id == round_id).first()
    if not row:
        raise HTTPException(404, "Exploration round not found")
    for field in data.model_fields:
        val = getattr(data, field)
        if field in ("started_at", "finished_at"):
            val = dt.fromisoformat(val)
        setattr(row, field, val)
    db.commit()
    db.refresh(row)
    return row


@router.post("/exploration-rounds", response_model=ExplorationRoundResponse)
def create_exploration_round(data: ExplorationRoundCreate, db: Session = Depends(get_db)):
    from datetime import datetime as dt
    row = ExplorationRound(
        round_number=data.round_number,
        mode=data.mode,
        started_at=dt.fromisoformat(data.started_at),
        finished_at=dt.fromisoformat(data.finished_at),
        experiment_ids=data.experiment_ids,
        total_experiments=data.total_experiments,
        total_strategies=data.total_strategies,
        profitable_count=data.profitable_count,
        profitability_pct=data.profitability_pct,
        std_a_count=data.std_a_count,
        best_strategy_name=data.best_strategy_name,
        best_strategy_score=data.best_strategy_score,
        best_strategy_return=data.best_strategy_return,
        best_strategy_dd=data.best_strategy_dd,
        insights=data.insights,
        promoted=data.promoted,
        issues_resolved=data.issues_resolved,
        next_suggestions=data.next_suggestions,
        summary=data.summary,
        memory_synced=data.memory_synced,
        pinecone_synced=data.pinecone_synced,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
