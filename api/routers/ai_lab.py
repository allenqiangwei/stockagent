"""AI Lab router — experiments, templates, strategy promotion."""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.ai_lab import StrategyTemplate, Experiment, ExperimentStrategy, ExplorationRound
from api.schemas.ai_lab import (
    TemplateCreate, TemplateUpdate, TemplateResponse,
    ExperimentCreate, ExperimentResponse, ExperimentListItem,
    CloneBacktestRequest, BatchCloneBacktestRequest, ComboExperimentCreate,
    ExplorationRoundCreate, ExplorationRoundResponse,
    GridSearchRequest,
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


@router.put("/experiments/{experiment_id}")
def update_experiment(experiment_id: int, data: dict, db: Session = Depends(get_db)):
    """Update experiment status (used by standalone processing scripts)."""
    exp = db.query(Experiment).get(experiment_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")
    if "status" in data:
        exp.status = data["status"]
    db.commit()
    return {"message": "Updated", "experiment_id": experiment_id}


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


@router.put("/strategies/{strategy_id}")
def update_experiment_strategy(
    strategy_id: int,
    data: dict,
    db: Session = Depends(get_db),
):
    """Update an experiment strategy's status and metrics (used by standalone processing scripts)."""
    exp_strat = db.query(ExperimentStrategy).get(strategy_id)
    if not exp_strat:
        raise HTTPException(404, "Experiment strategy not found")

    allowed = {
        "status", "score", "total_return_pct", "max_drawdown_pct",
        "total_trades", "win_rate", "sharpe_ratio", "avg_hold_days",
        "avg_pnl_pct", "regime_stats", "error_message", "profit_loss_ratio",
    }
    for key, val in data.items():
        if key in allowed:
            setattr(exp_strat, key, val)

    # If promoted, also update the formal strategy's backtest_summary
    if exp_strat.promoted and exp_strat.promoted_strategy_id:
        from api.models.strategy import Strategy
        formal = db.query(Strategy).get(exp_strat.promoted_strategy_id)
        if formal:
            plr_val = 0.0
            if exp_strat.backtest_run_id:
                from api.models.backtest import BacktestRun
                bt_run = db.query(BacktestRun).get(exp_strat.backtest_run_id)
                if bt_run and bt_run.profit_loss_ratio:
                    plr_val = bt_run.profit_loss_ratio
            formal.backtest_summary = {
                "score": exp_strat.score,
                "total_return_pct": exp_strat.total_return_pct,
                "max_drawdown_pct": exp_strat.max_drawdown_pct,
                "win_rate": exp_strat.win_rate,
                "total_trades": exp_strat.total_trades,
                "avg_hold_days": exp_strat.avg_hold_days,
                "avg_pnl_pct": exp_strat.avg_pnl_pct,
                "profit_loss_ratio": plr_val,
                "regime_stats": exp_strat.regime_stats,
            }

    db.commit()
    return {"message": "Updated", "strategy_id": strategy_id}


def _run_walk_forward_check(exp_strat, db) -> dict | None:
    """Run walk-forward validation on an experiment strategy.

    Returns dict with overfit_ratio, consistency_pct, test_avg_return, etc.
    Returns None if data unavailable or too few windows.
    """
    from datetime import timedelta
    from src.backtest.walk_forward import run_walk_forward
    from src.data_storage.database import DataCollector

    collector = DataCollector()
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")

    # Load stock data (same as batch-clone-backtest)
    stock_codes = collector.get_stocks_with_data(min_rows=60)
    stock_data = {}
    for code in stock_codes[:200]:  # Cap at 200 stocks for speed
        df = collector.get_daily_df(code, start_date, end_date, local_only=True)
        if df is not None and not df.empty and len(df) >= 60:
            stock_data[code] = df

    if len(stock_data) < 50:
        logger.warning("Walk-forward: insufficient stock data (%d), skipping", len(stock_data))
        return None

    # Build strategy dict
    strategy = {
        "name": exp_strat.name,
        "buy_conditions": exp_strat.buy_conditions or [],
        "sell_conditions": exp_strat.sell_conditions or [],
        "exit_config": exp_strat.exit_config or {},
    }

    # Run walk-forward: 2yr train, 6mo test, 6mo step
    wf = run_walk_forward(
        strategy=strategy,
        stock_data=stock_data,
        start_date=start_date,
        end_date=end_date,
        train_years=2.0,
        test_months=6,
        step_months=6,
    )

    if wf.total_rounds < 2:
        logger.info("Walk-forward: only %d rounds, insufficient for validation", wf.total_rounds)
        return None

    return {
        "total_rounds": wf.total_rounds,
        "test_avg_return": wf.test_avg_return,
        "test_avg_win_rate": wf.test_avg_win_rate,
        "test_avg_max_dd": wf.test_avg_max_dd,
        "train_avg_return": wf.train_avg_return,
        "overfit_ratio": wf.overfit_ratio,
        "consistency_pct": wf.consistency_pct,
        "profitable_rounds": wf.profitable_rounds,
        "test_total_trades": wf.test_total_trades,
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
    # Fetch PLR from the linked BacktestRun (ExperimentStrategy doesn't store it)
    plr_value = 0.0
    if exp_strat.backtest_run_id:
        from api.models.backtest import BacktestRun
        bt_run = db.query(BacktestRun).get(exp_strat.backtest_run_id)
        if bt_run and bt_run.profit_loss_ratio:
            plr_value = bt_run.profit_loss_ratio

    backtest_summary = {
        "score": exp_strat.score,
        "total_return_pct": exp_strat.total_return_pct,
        "max_drawdown_pct": exp_strat.max_drawdown_pct,
        "win_rate": exp_strat.win_rate,
        "total_trades": exp_strat.total_trades,
        "avg_hold_days": exp_strat.avg_hold_days,
        "avg_pnl_pct": exp_strat.avg_pnl_pct,
        "profit_loss_ratio": plr_value,
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

    # Compute fingerprint, skeleton, and indicator_family for competition check
    from api.services.strategy_pool import StrategyPoolManager, compute_fingerprint, _extract_skeleton, extract_indicator_family
    fingerprint = compute_fingerprint(
        exp_strat.buy_conditions or [], exp_strat.sell_conditions or []
    )
    skeleton = _extract_skeleton(base_name, exp_strat.buy_conditions, exp_strat.sell_conditions)
    indicator_family = extract_indicator_family(exp_strat.buy_conditions)
    pool_mgr = StrategyPoolManager(db)
    threshold, current_active, quota = pool_mgr.get_skeleton_competition_threshold(
        skeleton, indicator_family=indicator_family
    )

    new_score = exp_strat.score or 0
    can_compete = new_score > threshold

    # ── Walk-Forward Validation Gate ──────────────────────────────
    # Only for strategies that would enter the pool (can_compete=True).
    # Runs walk-forward to detect overfitting before activation.
    wf_result = None
    wf_passed = True  # default: pass if walk-forward is skipped

    if can_compete:
        try:
            wf_result = _run_walk_forward_check(exp_strat, db)
            if wf_result:
                # Fail if overfit or inconsistent
                if wf_result.get("overfit_ratio", 0) > 2.5:
                    wf_passed = False
                    logger.info(
                        "Walk-forward FAIL (overfit): S%d overfit_ratio=%.1f",
                        exp_strat.id, wf_result["overfit_ratio"],
                    )
                elif wf_result.get("consistency_pct", 100) < 40:
                    wf_passed = False
                    logger.info(
                        "Walk-forward FAIL (inconsistent): S%d consistency=%.1f%%",
                        exp_strat.id, wf_result["consistency_pct"],
                    )
                else:
                    logger.info(
                        "Walk-forward PASS: S%d overfit=%.1f consistency=%.1f%%",
                        exp_strat.id, wf_result["overfit_ratio"],
                        wf_result["consistency_pct"],
                    )
        except Exception as e:
            # Walk-forward failure should not block promote
            logger.warning("Walk-forward error for S%d, skipping: %s", exp_strat.id, e)

    # If walk-forward failed, archive instead of activating
    if not wf_passed:
        can_compete = False

    # Merge walk-forward metrics into backtest_summary
    if wf_result:
        backtest_summary["walk_forward"] = wf_result

    formal = Strategy(
        name=base_name,
        description=exp_strat.description,
        rules=[],
        buy_conditions=exp_strat.buy_conditions,
        sell_conditions=exp_strat.sell_conditions,
        exit_config=exp_strat.exit_config,
        weight=0.5,
        enabled=can_compete,
        category=resolved_category,
        backtest_summary=backtest_summary,
        source_experiment_id=exp_strat.id,
        signal_fingerprint=fingerprint,
        indicator_family=indicator_family,
        family_role="champion" if can_compete else "archive",
        archived_at=None if can_compete else datetime.now(),
    )
    db.add(formal)
    db.flush()

    exp_strat.promoted = True
    exp_strat.promoted_strategy_id = formal.id
    db.commit()

    if can_compete:
        return {
            "message": "Promoted and active (walk-forward passed)",
            "strategy_id": formal.id,
            "score": new_score,
            "skeleton_quota": quota,
            "skeleton_active": current_active + 1,
            "walk_forward": wf_result,
        }
    if wf_result and not wf_passed:
        return {
            "message": f"Promoted but archived — walk-forward failed (overfit={wf_result.get('overfit_ratio',0):.1f}, consistency={wf_result.get('consistency_pct',0):.1f}%)",
            "strategy_id": formal.id,
            "score": new_score,
            "walk_forward": wf_result,
            "can_compete": False,
        }
    return {
        "message": f"Promoted but archived — score {new_score:.4f} does not beat skeleton threshold {threshold:.4f} (quota={quota}, active={current_active})",
        "strategy_id": formal.id,
        "score": new_score,
        "threshold": threshold,
        "skeleton_quota": quota,
        "skeleton_active": current_active,
        "can_compete": False,
    }


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


# ── Batch Clone & Backtest ────────────────────────

@router.post("/strategies/{strategy_id}/batch-clone-backtest")
def batch_clone_and_backtest(
    strategy_id: int,
    req: BatchCloneBacktestRequest,
    db: Session = Depends(get_db),
):
    """Batch clone a strategy with N different exit configs and backtest all at once.

    Loads stock data + computes indicators + vectorizes signals ONCE,
    then runs N backtests using the optimized portfolio engine.
    10-50x faster than N individual clone-backtest calls.
    """
    import copy
    import threading
    from datetime import datetime, timedelta

    source = db.query(ExperimentStrategy).get(strategy_id)
    if not source:
        raise HTTPException(404, "Source experiment strategy not found")
    if source.status != "done":
        raise HTTPException(400, f"Source strategy status is '{source.status}', must be 'done'")

    if not req.exit_configs:
        raise HTTPException(400, "exit_configs list is empty")

    n = len(req.exit_configs)

    # Create one experiment for the entire batch
    exp = Experiment(
        theme=f"[批量调参] {source.name} ×{n}",
        source_type="batch-clone",
        source_text=f"批量克隆自 ExperimentStrategy ID{source.id} ({source.name}), {n} 组 exit_config",
        status="backtesting",
        strategy_count=n,
    )
    db.add(exp)
    db.flush()

    # Create all cloned strategies
    cloned_ids = []
    for cfg in req.exit_configs:
        suffix = cfg.get("name_suffix", "调参")
        exit_config = copy.deepcopy(source.exit_config or {})
        if cfg.get("exit_config"):
            exit_config.update(cfg["exit_config"])
        # Normalize stop_loss_pct
        if "stop_loss_pct" in exit_config and exit_config["stop_loss_pct"] is not None:
            exit_config["stop_loss_pct"] = -abs(exit_config["stop_loss_pct"])

        buy_conds = cfg["buy_conditions"] if "buy_conditions" in cfg else copy.deepcopy(source.buy_conditions)
        sell_conds = cfg["sell_conditions"] if "sell_conditions" in cfg else copy.deepcopy(source.sell_conditions)
        cloned = ExperimentStrategy(
            experiment_id=exp.id,
            name=f"{source.name}_{suffix}",
            description=f"批量克隆自 {source.name}, exit_config={json.dumps(exit_config)}",
            buy_conditions=buy_conds,
            sell_conditions=sell_conds,
            exit_config=exit_config,
            status="pending",
        )
        db.add(cloned)
        db.flush()
        cloned_ids.append(cloned.id)

    db.commit()
    exp_id = exp.id

    # Run batch backtest in background thread
    def _run_batch():
        import os
        import numpy as np
        from api.models.base import SessionLocal
        from api.services.ai_lab_engine import AILabEngine, _BACKTEST_SEMAPHORE, _compute_score
        from src.backtest.portfolio_engine import PortfolioBacktestEngine
        from src.backtest.vectorized_signals import vectorize_conditions

        _BACKTEST_SEMAPHORE.acquire()
        session = SessionLocal()
        try:
            engine = AILabEngine(session)
            experiment = session.query(Experiment).get(exp_id)

            # ── Load data ONCE ──
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")
            stock_codes = engine.collector.get_stocks_with_data(min_rows=60)
            stock_data = {}
            for code in stock_codes:
                df = engine.collector.get_daily_df(code, start_date, end_date, local_only=True)
                if df is not None and not df.empty and len(df) >= 60:
                    stock_data[code] = df

            if not stock_data:
                for sid in cloned_ids:
                    s = session.query(ExperimentStrategy).get(sid)
                    if s:
                        s.status = "failed"
                        s.error_message = "No stock data available"
                experiment.status = "failed"
                session.commit()
                return

            # Get regime map
            from api.services.regime_service import ensure_regimes, get_regime_map, get_regime_summary
            ensure_regimes(session, start_date, end_date)
            regime_map = get_regime_map(session, start_date, end_date)
            summary = get_regime_summary(session, start_date, end_date)
            index_return_pct = summary.get("total_index_return_pct", 0.0)

            # ── Prepare data ONCE for all cloned strategies ──
            from src.backtest.portfolio_engine import PortfolioBacktestEngine, SignalExplosionError, BacktestTimeoutError

            pe = PortfolioBacktestEngine(
                initial_capital=req.initial_capital,
                max_positions=req.max_positions,
                max_position_pct=req.max_position_pct,
            )

            # Build combined strategy dict for prepare_data — include indicators
            # from BOTH source and all clones so _revectorize can evaluate any condition
            source_strat = session.query(ExperimentStrategy).get(strategy_id)
            source_buy = source_strat.buy_conditions or []
            source_sell = source_strat.sell_conditions or []
            all_buy = list(source_buy)
            all_sell = list(source_sell)
            for sid in cloned_ids:
                cs = session.query(ExperimentStrategy).get(sid)
                if cs:
                    for c in (cs.buy_conditions or []):
                        if c not in all_buy:
                            all_buy.append(c)
                    for c in (cs.sell_conditions or []):
                        if c not in all_sell:
                            all_sell.append(c)
            strategy_dict = {
                "buy_conditions": all_buy,
                "sell_conditions": all_sell,
            }

            import time as _time
            t0 = _time.time()
            precomputed = pe.prepare_data(strategy_dict, stock_data)
            prep_time = _time.time() - t0
            import logging as _logging
            _log = _logging.getLogger(__name__)
            _log.info(
                "Batch prepare_data: %d stocks, %.1fs", len(stock_data), prep_time
            )

            if not precomputed["prepared"]:
                for sid in cloned_ids:
                    s = session.query(ExperimentStrategy).get(sid)
                    if s:
                        s.status = "failed"
                        s.error_message = "No prepared data after indicator computation"
                experiment.status = "failed"
                session.commit()
                return

            # Helper: re-vectorize signals when buy/sell conditions differ from source
            def _revectorize(buy_conds, sell_conds, precomputed_base):
                """Re-compute signal maps using different conditions on shared indicator data."""
                from src.backtest.vectorized_signals import vectorize_conditions
                from concurrent.futures import ThreadPoolExecutor
                prepared_data = precomputed_base["prepared"]
                n_workers = min(8, os.cpu_count() or 4)

                def _vbuy(args):
                    code, df = args
                    return code, vectorize_conditions(buy_conds, df, mode="AND")

                def _vsell(args):
                    code, df = args
                    if sell_conds:
                        return code, vectorize_conditions(sell_conds, df, mode="OR")
                    return code, np.zeros(len(df), dtype=bool)

                with ThreadPoolExecutor(max_workers=n_workers) as pool:
                    buy_map = dict(pool.map(_vbuy, prepared_data.items()))
                    sell_map = dict(pool.map(_vsell, prepared_data.items()))

                # T+1 shift
                for code in buy_map:
                    arr = buy_map[code]
                    shifted = np.zeros_like(arr)
                    shifted[1:] = arr[:-1]
                    buy_map[code] = shifted
                for code in sell_map:
                    arr = sell_map[code]
                    shifted = np.zeros_like(arr)
                    shifted[1:] = arr[:-1]
                    sell_map[code] = shifted

                return {
                    "prepared": prepared_data,
                    "sorted_dates": precomputed_base["sorted_dates"],
                    "stock_date_idx": precomputed_base["stock_date_idx"],
                    "buy_signal_map": buy_map,
                    "sell_signal_map": sell_map,
                }

            # Cache re-vectorized results by condition hash to avoid redundant work
            _cond_cache = {}

            # ── Run Phase 3 for each exit_config using shared data ──
            for i, sid in enumerate(cloned_ids):
                strat = session.query(ExperimentStrategy).get(sid)
                if not strat:
                    continue
                try:
                    strat.status = "backtesting"
                    session.commit()

                    # Check if this clone has different conditions
                    strat_buy = strat.buy_conditions or []
                    strat_sell = strat.sell_conditions or []
                    conds_match = (json.dumps(strat_buy, sort_keys=True) == json.dumps(source_buy, sort_keys=True)
                                   and json.dumps(strat_sell, sort_keys=True) == json.dumps(source_sell, sort_keys=True))

                    if conds_match:
                        run_precomputed = precomputed
                    else:
                        cond_key = json.dumps(strat_buy, sort_keys=True) + "|||" + json.dumps(strat_sell, sort_keys=True)
                        if cond_key not in _cond_cache:
                            t1 = _time.time()
                            _cond_cache[cond_key] = _revectorize(strat_buy, strat_sell, precomputed)
                            _log.info("Re-vectorized signals for %s: %.1fs", strat.name[:50], _time.time() - t1)
                        run_precomputed = _cond_cache[cond_key]

                    exit_cfg = strat.exit_config or {}
                    cancel_event = threading.Event()
                    timer = threading.Timer(300, cancel_event.set)
                    timer.daemon = True
                    timer.start()

                    try:
                        result = pe.run_with_prepared(
                            strategy_name=strat.name,
                            exit_config=exit_cfg,
                            precomputed=run_precomputed,
                            regime_map=regime_map,
                            cancel_event=cancel_event,
                        )
                    except (SignalExplosionError, BacktestTimeoutError) as e:
                        strat.status = "invalid"
                        strat.error_message = str(e)[:500]
                        strat.score = 0.0
                        session.commit()
                        continue
                    finally:
                        timer.cancel()

                    # Score the result
                    strat.total_trades = result.total_trades
                    strat.win_rate = result.win_rate
                    strat.total_return_pct = result.total_return_pct
                    strat.max_drawdown_pct = result.max_drawdown_pct
                    strat.avg_hold_days = result.avg_hold_days
                    strat.avg_pnl_pct = result.avg_pnl_pct
                    strat.regime_stats = result.regime_stats if result.regime_stats else None

                    if result.total_trades == 0:
                        strat.score = 0.0
                        strat.status = "invalid"
                        strat.error_message = "零交易"
                    else:
                        from api.config import get_settings
                        lab_cfg = get_settings().ai_lab
                        weights = {
                            "weight_return": lab_cfg.weight_return,
                            "weight_drawdown": lab_cfg.weight_drawdown,
                            "weight_sharpe": lab_cfg.weight_sharpe,
                            "weight_plr": lab_cfg.weight_plr,
                        }
                        strat.score = round(_compute_score(result, weights), 4)
                        strat.status = "done"

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    strat.status = "failed"
                    strat.error_message = str(e)[:500]
                session.commit()

            experiment.status = "done"
            session.commit()
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                exp_obj = session.query(Experiment).get(exp_id)
                if exp_obj:
                    exp_obj.status = "failed"
                session.commit()
            except Exception:
                session.rollback()
        finally:
            _BACKTEST_SEMAPHORE.release()
            session.close()

    threading.Thread(target=_run_batch, daemon=True).start()

    return {
        "message": f"Batch clone created: {n} strategies, backtest started",
        "experiment_id": exp.id,
        "strategy_ids": cloned_ids,
        "count": n,
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


# ── Grid Search ──────────────────────────────────

@router.post("/strategies/{strategy_id}/grid-search")
def grid_search(
    strategy_id: int,
    req: GridSearchRequest,
    db: Session = Depends(get_db),
):
    """Parameter grid search: systematically test all SL/TP/MHD combinations.

    Uses prepare_data() once + run_with_prepared() per combination.
    Returns results matrix sorted by score, with StdA+ flag.
    """
    import itertools
    import threading

    source = db.query(ExperimentStrategy).get(strategy_id)
    if not source:
        raise HTTPException(404, "Source experiment strategy not found")
    if source.status != "done":
        raise HTTPException(400, f"Source strategy status is '{source.status}', must be 'done'")

    # Generate all combinations
    combos = list(itertools.product(
        req.stop_loss_values,
        req.take_profit_values,
        req.max_hold_days_values,
    ))
    n = len(combos)
    if n > 500:
        raise HTTPException(400, f"Too many combinations ({n}), max 500. Reduce parameter ranges.")

    # Build exit_configs for batch-clone-backtest
    exit_configs = []
    for sl, tp, mhd in combos:
        sl_neg = -abs(sl)
        suffix = f"SL{abs(sl)}_TP{tp}_MHD{mhd}"
        exit_configs.append({
            "name_suffix": suffix,
            "exit_config": {
                "stop_loss_pct": sl_neg,
                "take_profit_pct": tp,
                "max_hold_days": mhd,
            },
        })

    # Create experiment
    exp = Experiment(
        theme=f"[网格搜索] {source.name} ×{n}",
        source_type="grid-search",
        source_text=f"网格搜索: SL={req.stop_loss_values}, TP={req.take_profit_values}, MHD={req.max_hold_days_values}",
        status="backtesting",
        strategy_count=n,
    )
    db.add(exp)
    db.flush()

    # Create cloned strategies
    import copy
    source_buy = source.buy_conditions or []
    source_sell = source.sell_conditions or []
    cloned_ids = []
    for cfg in exit_configs:
        exit_config = copy.deepcopy(source.exit_config or {})
        exit_config.update(cfg["exit_config"])
        cloned = ExperimentStrategy(
            experiment_id=exp.id,
            name=f"{source.name}_{cfg['name_suffix']}",
            description=f"网格搜索: {json.dumps(exit_config)}",
            buy_conditions=copy.deepcopy(source_buy),
            sell_conditions=copy.deepcopy(source_sell),
            exit_config=exit_config,
            status="pending",
        )
        db.add(cloned)
        db.flush()
        cloned_ids.append(cloned.id)

    db.commit()
    exp_id = exp.id

    # Background thread: prepare once, run N times
    def _run_grid():
        import os
        import time as _time
        import numpy as np
        import logging as _logging
        from datetime import timedelta
        from api.models.base import SessionLocal
        from api.services.ai_lab_engine import AILabEngine, _BACKTEST_SEMAPHORE, _compute_score
        from src.backtest.portfolio_engine import (
            PortfolioBacktestEngine, SignalExplosionError, BacktestTimeoutError,
        )

        _log = _logging.getLogger(__name__)
        _BACKTEST_SEMAPHORE.acquire()
        session = SessionLocal()
        try:
            engine = AILabEngine(session)
            experiment = session.query(Experiment).get(exp_id)

            # Load data
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")
            stock_codes = engine.collector.get_stocks_with_data(min_rows=60)
            stock_data = {}
            for code in stock_codes:
                df = engine.collector.get_daily_df(code, start_date, end_date, local_only=True)
                if df is not None and not df.empty and len(df) >= 60:
                    stock_data[code] = df

            if not stock_data:
                for sid in cloned_ids:
                    s = session.query(ExperimentStrategy).get(sid)
                    if s:
                        s.status = "failed"
                        s.error_message = "No stock data"
                experiment.status = "failed"
                session.commit()
                return

            # Regime map
            from api.services.regime_service import ensure_regimes, get_regime_map
            ensure_regimes(session, start_date, end_date)
            regime_map = get_regime_map(session, start_date, end_date)

            # Prepare data ONCE
            pe = PortfolioBacktestEngine(
                initial_capital=req.initial_capital,
                max_positions=req.max_positions,
                max_position_pct=req.max_position_pct,
            )
            strategy_dict = {"buy_conditions": source_buy, "sell_conditions": source_sell}

            t0 = _time.time()
            precomputed = pe.prepare_data(strategy_dict, stock_data)
            _log.info("Grid search prepare_data: %d stocks, %.1fs", len(stock_data), _time.time() - t0)

            if not precomputed["prepared"]:
                for sid in cloned_ids:
                    s = session.query(ExperimentStrategy).get(sid)
                    if s:
                        s.status = "failed"
                        s.error_message = "No prepared data"
                experiment.status = "failed"
                session.commit()
                return

            # Run each combination
            from api.config import get_settings
            lab_cfg = get_settings().ai_lab
            weights = {
                "weight_return": lab_cfg.weight_return,
                "weight_drawdown": lab_cfg.weight_drawdown,
                "weight_sharpe": lab_cfg.weight_sharpe,
                "weight_plr": lab_cfg.weight_plr,
            }

            for i, sid in enumerate(cloned_ids):
                strat = session.query(ExperimentStrategy).get(sid)
                if not strat:
                    continue
                try:
                    strat.status = "backtesting"
                    session.commit()

                    cancel_event = threading.Event()
                    timer = threading.Timer(300, cancel_event.set)
                    timer.daemon = True
                    timer.start()

                    try:
                        result = pe.run_with_prepared(
                            strategy_name=strat.name,
                            exit_config=strat.exit_config or {},
                            precomputed=precomputed,
                            regime_map=regime_map,
                            cancel_event=cancel_event,
                        )
                    except (SignalExplosionError, BacktestTimeoutError) as e:
                        strat.status = "invalid"
                        strat.error_message = str(e)[:500]
                        strat.score = 0.0
                        session.commit()
                        continue
                    finally:
                        timer.cancel()

                    strat.total_trades = result.total_trades
                    strat.win_rate = result.win_rate
                    strat.total_return_pct = result.total_return_pct
                    strat.max_drawdown_pct = result.max_drawdown_pct
                    strat.avg_hold_days = result.avg_hold_days
                    strat.avg_pnl_pct = result.avg_pnl_pct
                    strat.regime_stats = result.regime_stats if result.regime_stats else None

                    if result.total_trades == 0:
                        strat.score = 0.0
                        strat.status = "invalid"
                        strat.error_message = "零交易"
                    else:
                        strat.score = round(_compute_score(result, weights), 4)
                        strat.status = "done"

                    if (i + 1) % 10 == 0:
                        _log.info("Grid search progress: %d/%d", i + 1, n)

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    strat.status = "failed"
                    strat.error_message = str(e)[:500]
                session.commit()

            experiment.status = "done"
            session.commit()
            _log.info("Grid search done: %d combinations for %s", n, source.name)

        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                exp_obj = session.query(Experiment).get(exp_id)
                if exp_obj:
                    exp_obj.status = "failed"
                session.commit()
            except Exception:
                session.rollback()
        finally:
            _BACKTEST_SEMAPHORE.release()
            session.close()

    threading.Thread(target=_run_grid, daemon=True).start()

    return {
        "message": f"网格搜索已启动: {n} 个参数组合",
        "experiment_id": exp.id,
        "strategy_ids": cloned_ids,
        "combinations": n,
        "params": {
            "stop_loss": req.stop_loss_values,
            "take_profit": req.take_profit_values,
            "max_hold_days": req.max_hold_days_values,
        },
    }


@router.get("/strategies/{strategy_id}/grid-results")
def get_grid_results(
    strategy_id: int,
    db: Session = Depends(get_db),
):
    """Get grid search results for a strategy, sorted by score.

    Returns all combinations with metrics and StdA+ flag.
    """
    # Find grid-search experiments for this source strategy
    experiments = (
        db.query(Experiment)
        .filter(
            Experiment.source_type == "grid-search",
            Experiment.source_text.contains(f"ID{strategy_id}") | Experiment.theme.contains(f"#{strategy_id}"),
        )
        .order_by(Experiment.id.desc())
        .all()
    )

    # Also match by looking at the strategies in grid-search experiments
    # that share the same buy_conditions as the source
    source = db.query(ExperimentStrategy).get(strategy_id)
    if not source:
        raise HTTPException(404, "Source strategy not found")

    # Find all grid-search experiments that contain clones of this source
    grid_exps = (
        db.query(Experiment)
        .filter(Experiment.source_type == "grid-search")
        .order_by(Experiment.id.desc())
        .limit(20)
        .all()
    )

    results = []
    for exp in grid_exps:
        strategies = (
            db.query(ExperimentStrategy)
            .filter(
                ExperimentStrategy.experiment_id == exp.id,
                ExperimentStrategy.status == "done",
            )
            .order_by(ExperimentStrategy.score.desc())
            .all()
        )
        if not strategies:
            continue

        # Check if this experiment is for the same source by matching buy_conditions
        first = strategies[0]
        if json.dumps(first.buy_conditions, sort_keys=True) != json.dumps(source.buy_conditions, sort_keys=True):
            continue

        for s in strategies:
            ec = s.exit_config or {}
            plr = 0
            if s.total_trades and s.total_trades > 0:
                bs = s.regime_stats or {}
                # PLR is stored in the name pattern; recalculate from score components
                # Actually we need to get it from backtest result — check if it's in regime_stats
                pass

            is_stda = (
                (s.score or 0) >= 0.80
                and (s.total_return_pct or 0) > 60
                and abs(s.max_drawdown_pct or 0) < 18
                and (s.total_trades or 0) >= 50
                and (s.win_rate or 0) > 60
            )

            results.append({
                "id": s.id,
                "name": s.name,
                "experiment_id": exp.id,
                "stop_loss_pct": ec.get("stop_loss_pct"),
                "take_profit_pct": ec.get("take_profit_pct"),
                "max_hold_days": ec.get("max_hold_days"),
                "score": round(s.score or 0, 4),
                "total_return_pct": round(s.total_return_pct or 0, 2),
                "max_drawdown_pct": round(s.max_drawdown_pct or 0, 2),
                "win_rate": round(s.win_rate or 0, 2),
                "total_trades": s.total_trades or 0,
                "avg_hold_days": round(s.avg_hold_days or 0, 1),
                "avg_pnl_pct": round(s.avg_pnl_pct or 0, 2),
                "is_stda_plus": is_stda,
                "status": s.status,
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    stda_count = sum(1 for r in results if r["is_stda_plus"])
    return {
        "source_strategy_id": strategy_id,
        "source_name": source.name,
        "total_combinations": len(results),
        "stda_plus_count": stda_count,
        "results": results,
    }
