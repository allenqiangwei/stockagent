#!/usr/bin/env python3
"""R1189: Fast batch backtest processor.

Loads stock data ONCE, groups experiment strategies by buy/sell conditions,
calls prepare_data() once per family, then run_with_prepared() for each variant.
5-10x faster than the retry-pending sequential approach.

Usage:
    cd /Users/allenqiang/stockagent
    NO_PROXY=localhost,127.0.0.1 nohup python3 scripts/r1189_fast_process.py > /tmp/r1189_fast.log 2>&1 &
"""

import json
import logging
import math
import os
import sys
import threading
import time
import urllib.parse
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_db_session():
    from api.models.base import SessionLocal
    return SessionLocal()


def sigmoid(x, center=0, scale=1):
    z = (x - center) / scale
    return 1 / (1 + math.exp(-z))


def compute_score(result) -> float:
    w_ret, w_dd, w_sharpe, w_plr = 0.30, 0.25, 0.25, 0.20
    ret_score = sigmoid(result.total_return_pct, center=0, scale=30)
    dd = abs(result.max_drawdown_pct) if result.max_drawdown_pct else 0
    dd_score = 1 - sigmoid(dd, center=30, scale=15)
    sharpe = result.sharpe_ratio if result.sharpe_ratio else 0
    sharpe_score = sigmoid(sharpe, center=0, scale=1.5)
    plr = result.profit_loss_ratio if result.profit_loss_ratio else 0
    plr_score = sigmoid(plr, center=1.0, scale=1.5)
    score = w_ret * ret_score + w_dd * dd_score + w_sharpe * sharpe_score + w_plr * plr_score
    if dd > 80:
        score *= 0.5
    return round(score, 4)


def load_experiment_ids():
    """Load R1189 experiment IDs."""
    with open('/tmp/r1189_experiment_ids.json') as f:
        return json.load(f)['experiment_ids']


def group_experiment_strategies(session, experiment_ids):
    """Group experiment strategies by buy+sell conditions (family)."""
    from api.models.ai_lab import ExperimentStrategy, Experiment

    families = defaultdict(list)
    total = 0
    pending = 0

    for eid in experiment_ids:
        strategies = (
            session.query(ExperimentStrategy)
            .filter(ExperimentStrategy.experiment_id == eid)
            .all()
        )
        for s in strategies:
            total += 1
            if s.status in ('pending', 'backtesting'):
                pending += 1
                key = json.dumps(s.buy_conditions or [], sort_keys=True) + "|||" + \
                      json.dumps(s.sell_conditions or [], sort_keys=True)
                families[key].append(s)

    logger.info("Total strategies: %d, Pending: %d, Families: %d", total, pending, len(families))
    return sorted(families.values(), key=lambda v: len(v), reverse=True)


def load_stock_data(session, start_date, end_date):
    from api.services.data_collector import DataCollector
    collector = DataCollector(session)
    stock_codes = collector.get_stocks_with_data(min_rows=60)
    logger.info("Found %d stocks", len(stock_codes))

    stock_data = {}
    for i, code in enumerate(stock_codes):
        df = collector.get_daily_df(code, start_date, end_date, local_only=True)
        if df is not None and not df.empty and len(df) >= 60:
            stock_data[code] = df
        if (i + 1) % 500 == 0:
            logger.info("  Loaded %d/%d stocks...", i + 1, len(stock_codes))

    logger.info("Loaded %d stocks with valid data", len(stock_data))
    return stock_data


def load_regime_map(session, start_date, end_date):
    from api.services.regime_service import ensure_regimes, get_regime_map
    ensure_regimes(session, start_date, end_date)
    return get_regime_map(session, start_date, end_date)


def run_family(family, stock_data, regime_map, session):
    """Run backtest for one family of experiment strategies."""
    from src.backtest.portfolio_engine import (
        PortfolioBacktestEngine, SignalExplosionError, BacktestTimeoutError,
    )

    representative = family[0]
    family_name = representative.name.split("_SL")[0].split("_TP")[0][:50] if representative.name else f"ES{representative.id}"

    strategy_dict = {
        "buy_conditions": representative.buy_conditions or [],
        "sell_conditions": representative.sell_conditions or [],
    }

    pe = PortfolioBacktestEngine(
        initial_capital=100000,
        max_positions=10,
        max_position_pct=30,
        slippage_pct=0.1,
    )

    t0 = time.time()
    try:
        precomputed = pe.prepare_data(strategy_dict, stock_data)
    except Exception as e:
        logger.error("  Family '%s': prepare_data error: %s", family_name, str(e)[:200])
        for s in family:
            s.status = "failed"
            s.error_message = f"prepare_data error: {str(e)[:200]}"
        session.commit()
        return {"done": 0, "failed": len(family), "invalid": 0, "stda": 0}

    prep_time = time.time() - t0

    if not precomputed.get("prepared"):
        logger.warning("  Family '%s': No prepared data, skipping %d strategies", family_name, len(family))
        for s in family:
            s.status = "invalid"
            s.error_message = "No prepared data"
        session.commit()
        return {"done": 0, "failed": 0, "invalid": len(family), "stda": 0}

    logger.info("  prepare_data: %.1fs, %d stocks", prep_time, len(precomputed.get("prepared", {})))

    stats = {"done": 0, "failed": 0, "invalid": 0, "stda": 0}

    for i, strat in enumerate(family):
        exit_config = strat.exit_config or {}

        try:
            cancel_event = threading.Event()
            timer = threading.Timer(600, cancel_event.set)
            timer.daemon = True
            timer.start()

            try:
                result = pe.run_with_prepared(
                    strategy_name=strat.name or f"ES{strat.id}",
                    exit_config=exit_config,
                    precomputed=precomputed,
                    regime_map=regime_map,
                    cancel_event=cancel_event,
                )
            except (SignalExplosionError, BacktestTimeoutError) as e:
                logger.warning("  ES%d: %s", strat.id, str(e)[:80])
                strat.status = "invalid"
                strat.error_message = str(e)[:200]
                strat.score = 0
                stats["invalid"] += 1
                continue
            finally:
                timer.cancel()

            if result.total_trades == 0:
                strat.status = "invalid"
                strat.error_message = "zero trades"
                strat.score = 0
                stats["invalid"] += 1
                continue

            score = compute_score(result)

            strat.status = "done"
            strat.score = score
            strat.total_trades = result.total_trades
            strat.win_rate = round(result.win_rate, 2)
            strat.total_return_pct = round(result.total_return_pct, 2)
            strat.max_drawdown_pct = round(result.max_drawdown_pct, 2)
            strat.avg_hold_days = round(result.avg_hold_days, 1)
            strat.avg_pnl_pct = round(result.avg_pnl_pct, 2)
            strat.regime_stats = result.regime_stats or {}
            strat.backtest_run_id = getattr(result, 'run_id', None)

            stats["done"] += 1

            dd = abs(result.max_drawdown_pct)
            if score >= 0.80 and result.total_return_pct > 60 and dd < 18 and result.total_trades >= 50 and result.win_rate > 60:
                stats["stda"] += 1

            if (i + 1) % 20 == 0:
                session.commit()

        except Exception as e:
            logger.error("  ES%d ERROR: %s", strat.id, str(e)[:200])
            strat.status = "failed"
            strat.error_message = str(e)[:200]
            stats["failed"] += 1

    session.commit()

    # Update experiment status if all strategies done
    exp_ids = set(s.experiment_id for s in family)
    from api.models.ai_lab import Experiment
    for eid in exp_ids:
        exp = session.query(Experiment).get(eid)
        if exp:
            from api.models.ai_lab import ExperimentStrategy as ES
            remaining = session.query(ES).filter(
                ES.experiment_id == eid,
                ES.status.in_(['pending', 'backtesting'])
            ).count()
            if remaining == 0:
                exp.status = "done"
                # Update best score
                best = session.query(ES).filter(
                    ES.experiment_id == eid, ES.status == 'done'
                ).order_by(ES.score.desc()).first()
                if best:
                    exp.best_score = best.score
                    exp.best_name = best.name
    session.commit()

    return stats


def promote_all(session, experiment_ids):
    """Promote StdA+ strategies via API."""
    from api.models.ai_lab import ExperimentStrategy

    promoted = []
    for eid in experiment_ids:
        strategies = session.query(ExperimentStrategy).filter(
            ExperimentStrategy.experiment_id == eid,
            ExperimentStrategy.status == 'done',
        ).all()

        for s in strategies:
            if s.promoted:
                continue
            score = s.score or 0
            ret = s.total_return_pct or 0
            dd = abs(s.max_drawdown_pct or 100)
            trades = s.total_trades or 0
            wr = s.win_rate or 0
            if score >= 0.80 and ret > 60 and dd < 18 and trades >= 50 and wr > 60:
                # Promote via API
                encoded_label = urllib.parse.quote('[AI]')
                encoded_cat = urllib.parse.quote('全能')
                r = subprocess.run(
                    ['curl', '-s', '-X', 'POST',
                     f'http://127.0.0.1:8050/api/lab/strategies/{s.id}/promote?label={encoded_label}&category={encoded_cat}'],
                    capture_output=True, text=True,
                    env={'NO_PROXY': 'localhost,127.0.0.1', 'PATH': '/usr/bin:/bin'})
                try:
                    result = json.loads(r.stdout)
                    msg = result.get('message', '')
                    if msg != 'Already promoted':
                        promoted.append({'id': s.id, 'name': s.name[:60], 'score': score})
                except:
                    pass

    return promoted


def main():
    logger.info("=" * 60)
    logger.info("R1189 Fast Batch Processor")
    logger.info("=" * 60)

    session = get_db_session()

    # Load experiment IDs
    experiment_ids = load_experiment_ids()
    logger.info("Loaded %d experiment IDs", len(experiment_ids))

    # Date range
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")
    logger.info("Period: %s → %s", start_date, end_date)

    # Step 1: Group strategies by family
    logger.info("\n[Step 1] Grouping experiment strategies...")
    families = group_experiment_strategies(session, experiment_ids)
    total_pending = sum(len(f) for f in families)
    logger.info("  %d families, %d pending strategies", len(families), total_pending)

    # Step 2: Load stock data (ONCE)
    logger.info("\n[Step 2] Loading stock data (shared)...")
    t0 = time.time()
    stock_data = load_stock_data(session, start_date, end_date)
    logger.info("  Stock data loaded in %.1fs", time.time() - t0)

    # Step 3: Load regime map
    logger.info("\n[Step 3] Loading regime map...")
    regime_map = load_regime_map(session, start_date, end_date)

    # Step 4: Process families
    logger.info("\n[Step 4] Processing %d families...", len(families))
    total_stats = {"done": 0, "failed": 0, "invalid": 0, "stda": 0}
    t_start = time.time()

    for fi, family in enumerate(families, 1):
        rep = family[0]
        fname = rep.name[:50] if rep.name else f"ES{rep.id}"
        logger.info("[%d/%d] Family '%s' (%d strategies)", fi, len(families), fname, len(family))

        stats = run_family(family, stock_data, regime_map, session)

        for k in total_stats:
            total_stats[k] += stats[k]

        elapsed = time.time() - t_start
        done_so_far = total_stats["done"] + total_stats["invalid"] + total_stats["failed"]
        rate = done_so_far / max(elapsed, 1) * 60
        remaining = total_pending - done_so_far
        eta_min = remaining / max(rate, 0.1)

        logger.info("  → done=%d inv=%d fail=%d stda=%d | Total: %d/%d (%.0f/min, ETA %.0fmin)",
                     stats["done"], stats["invalid"], stats["failed"], stats["stda"],
                     done_so_far, total_pending, rate, eta_min)

    elapsed_total = time.time() - t_start

    # Step 5: Promote StdA+
    logger.info("\n[Step 5] Promoting StdA+ strategies...")
    promoted = promote_all(session, experiment_ids)
    logger.info("  Promoted %d new strategies", len(promoted))

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("R1189 FAST PROCESS COMPLETE")
    logger.info("  Time: %.1f min", elapsed_total / 60)
    logger.info("  Done: %d", total_stats["done"])
    logger.info("  Invalid: %d", total_stats["invalid"])
    logger.info("  Failed: %d", total_stats["failed"])
    logger.info("  StdA+: %d", total_stats["stda"])
    logger.info("  Promoted: %d", len(promoted))
    logger.info("=" * 60)

    # Save summary
    summary = {
        'round': 1189,
        'time_min': round(elapsed_total / 60, 1),
        'done': total_stats['done'],
        'invalid': total_stats['invalid'],
        'failed': total_stats['failed'],
        'stda': total_stats['stda'],
        'promoted': len(promoted),
        'promoted_list': promoted[:50],
    }
    with open('/tmp/r1189_summary.json', 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    session.close()


if __name__ == "__main__":
    main()
