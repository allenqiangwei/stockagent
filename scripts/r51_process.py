#!/usr/bin/env python3
"""Process R51 experiments: run pending backtests directly.

Bypasses AILabEngine's daemon thread (which has foreign key issues).
Uses PortfolioBacktestEngine directly, similar to mass_rebacktest.py.

Usage:
    cd /Users/allenqiang/stockagent
    NO_PROXY=localhost,127.0.0.1 /Users/allenqiang/stockagent/venv/bin/python3 scripts/r51_process.py
"""

import json
import logging
import math
import os
import sys
import threading
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

R51_EXPERIMENT_IDS = [3381, 3382, 3383, 3384, 3385, 3386, 3387]


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


def main():
    from api.models.base import SessionLocal
    from api.models.ai_lab import Experiment, ExperimentStrategy
    from api.services.data_collector import DataCollector
    from api.services.regime_service import ensure_regimes, get_regime_map
    from src.backtest.portfolio_engine import (
        PortfolioBacktestEngine, SignalExplosionError, BacktestTimeoutError,
    )

    db = SessionLocal()

    # Load stock data and regime map (once for all experiments)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365 * 3 + 30)).strftime("%Y-%m-%d")

    logger.info("Loading stock data (%s to %s)...", start_date, end_date)
    collector = DataCollector(db)
    stock_codes = collector.get_stocks_with_data(min_rows=60)
    logger.info("Found %d stocks", len(stock_codes))

    stock_data = {}
    for i, code in enumerate(stock_codes):
        df = collector.get_daily_df(code, start_date, end_date, local_only=True)
        if df is not None and not df.empty and len(df) >= 60:
            stock_data[code] = df
        if (i + 1) % 1000 == 0:
            logger.info("  Loaded %d/%d stocks...", i + 1, len(stock_codes))
    logger.info("Loaded %d stocks with valid data", len(stock_data))

    logger.info("Loading regime map...")
    ensure_regimes(db, start_date, end_date)
    regime_map = get_regime_map(db, start_date, end_date)
    logger.info("Regime map loaded: %d entries", len(regime_map))

    # Process each experiment
    total_done = 0
    total_invalid = 0
    total_stda = 0

    # Group experiments by their buy/sell conditions to share prepare_data
    family_groups = {}  # key -> [(exp_id, strategy)]

    for eid in R51_EXPERIMENT_IDS:
        exp = db.get(Experiment, eid)
        if not exp:
            logger.warning("E%d not found, skipping", eid)
            continue

        for strat in exp.strategies:
            if strat.status != 'pending':
                continue
            buy_conds = json.dumps(strat.buy_conditions or [], sort_keys=True)
            sell_conds = json.dumps(strat.sell_conditions or [], sort_keys=True)
            key = buy_conds + "|||" + sell_conds
            if key not in family_groups:
                family_groups[key] = []
            family_groups[key].append((eid, strat))

    logger.info("Found %d strategy families across %d experiments",
                len(family_groups), len(R51_EXPERIMENT_IDS))

    for fam_idx, (key, members) in enumerate(family_groups.items()):
        representative = members[0][1]
        strategy_dict = {
            "buy_conditions": representative.buy_conditions or [],
            "sell_conditions": representative.sell_conditions or [],
        }
        fam_name = representative.name.split("_SL")[0][:40]

        logger.info("[Family %d/%d] '%s' — %d strategies",
                    fam_idx + 1, len(family_groups), fam_name, len(members))

        # Phase 1: prepare_data (once per family)
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
            logger.error("  prepare_data error: %s", e)
            # Mark all as invalid
            for eid, strat in members:
                strat.status = 'invalid'
                total_invalid += 1
            db.commit()
            continue

        prep_time = time.time() - t0

        if not precomputed.get("prepared"):
            logger.warning("  No prepared data, marking %d as invalid", len(members))
            for eid, strat in members:
                strat.status = 'invalid'
                total_invalid += 1
            db.commit()
            continue

        logger.info("  prepare_data: %.1fs, %d stocks",
                    prep_time, len(precomputed["prepared"]))

        # Phase 2: run_with_prepared for each strategy
        for eid, strat in members:
            strat.status = 'backtesting'
            db.commit()

            exit_config = strat.exit_config or {}

            try:
                cancel_event = threading.Event()
                timer = threading.Timer(600, cancel_event.set)
                timer.daemon = True
                timer.start()

                try:
                    result = pe.run_with_prepared(
                        strategy_name=strat.name,
                        exit_config=exit_config,
                        precomputed=precomputed,
                        regime_map=regime_map,
                        cancel_event=cancel_event,
                    )
                finally:
                    timer.cancel()

                if cancel_event.is_set():
                    logger.warning("  ES%d: timeout", strat.id)
                    strat.status = 'invalid'
                    total_invalid += 1
                    db.commit()
                    continue

                # Save results
                strat.total_return_pct = float(result.total_return_pct or 0)
                strat.max_drawdown_pct = float(result.max_drawdown_pct or 0)
                strat.total_trades = int(result.total_trades or 0)
                strat.win_rate = float(result.win_rate or 0)
                strat.avg_hold_days = float(getattr(result, 'avg_hold_days', 0) or 0)
                strat.score = compute_score(result)
                strat.regime_stats = getattr(result, 'regime_stats', None)
                strat.status = 'done'
                total_done += 1

                score = strat.score
                ret = strat.total_return_pct or 0
                dd = abs(strat.max_drawdown_pct or 0)
                trades = strat.total_trades or 0

                if score >= 0.75 and ret > 60 and dd < 18 and trades >= 50:
                    total_stda += 1
                    logger.info("  ES%d: DONE score=%.3f ret=%+.1f%% dd=%.1f%% trades=%d ★StdA+",
                                strat.id, score, ret, dd, trades)
                else:
                    logger.info("  ES%d: DONE score=%.3f ret=%+.1f%% dd=%.1f%% trades=%d",
                                strat.id, score, ret, dd, trades)

            except (SignalExplosionError, BacktestTimeoutError) as e:
                logger.warning("  ES%d: %s", strat.id, str(e)[:80])
                strat.status = 'invalid'
                total_invalid += 1

            except Exception as e:
                logger.error("  ES%d: error: %s", strat.id, str(e)[:100])
                strat.status = 'invalid'
                total_invalid += 1

            db.commit()

    # Mark experiments as done
    for eid in R51_EXPERIMENT_IDS:
        exp = db.get(Experiment, eid)
        if exp and exp.status == 'backtesting':
            pending = [s for s in exp.strategies if s.status == 'pending']
            if not pending:
                exp.status = 'done'
    db.commit()

    logger.info("=" * 60)
    logger.info("R51 COMPLETE: %d done, %d invalid, %d StdA+", total_done, total_invalid, total_stda)

    db.close()


if __name__ == "__main__":
    main()
