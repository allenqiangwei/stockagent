#!/usr/bin/env python3
"""Mass re-backtest all strategies in the library with the T+1 engine.

Groups strategies by buy/sell conditions (families), calls prepare_data() once
per family, then run_with_prepared() for each exit_config variant.

Usage:
    cd /Users/allenqiang/stockagent && source venv/bin/activate
    NO_PROXY=localhost,127.0.0.1 python scripts/mass_rebacktest.py [--dry-run] [--family-id N]
"""

import argparse
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_db_session():
    """Create a database session."""
    from api.models.base import SessionLocal
    return SessionLocal()


def sigmoid(x, center=0, scale=1):
    """Sigmoid normalization → [0, 1]."""
    z = (x - center) / scale
    return 1 / (1 + math.exp(-z))


def compute_score(result) -> float:
    """Compute composite score matching _compute_score in ai_lab_engine."""
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


def group_strategies(session):
    """Group strategies by buy_conditions + sell_conditions (same rules = same family)."""
    from api.models.strategy import Strategy

    strategies = session.query(Strategy).all()
    families = defaultdict(list)

    for s in strategies:
        key = json.dumps(s.buy_conditions or [], sort_keys=True) + "|||" + \
              json.dumps(s.sell_conditions or [], sort_keys=True)
        families[key].append(s)

    # Sort families by size (largest first for progress visibility)
    sorted_families = sorted(families.values(), key=lambda v: len(v), reverse=True)
    return sorted_families


def load_stock_data(session, start_date: str, end_date: str):
    """Load all stock data for the backtest period."""
    from api.services.data_collector import DataCollector

    collector = DataCollector(session)
    stock_codes = collector.get_stocks_with_data(min_rows=60)
    logger.info("Found %d stocks with sufficient data", len(stock_codes))

    stock_data = {}
    for i, code in enumerate(stock_codes):
        df = collector.get_daily_df(code, start_date, end_date, local_only=True)
        if df is not None and not df.empty and len(df) >= 60:
            stock_data[code] = df
        if (i + 1) % 500 == 0:
            logger.info("  Loaded %d/%d stocks...", i + 1, len(stock_codes))

    logger.info("Loaded %d stocks with valid data", len(stock_data))
    return stock_data


def load_regime_map(session, start_date: str, end_date: str):
    """Load market regime map."""
    from api.services.regime_service import ensure_regimes, get_regime_map
    ensure_regimes(session, start_date, end_date)
    return get_regime_map(session, start_date, end_date)


def run_family(family, stock_data, regime_map, session, dry_run=False):
    """Run backtest for one family of strategies (shared buy/sell conditions)."""
    from src.backtest.portfolio_engine import (
        PortfolioBacktestEngine, SignalExplosionError, BacktestTimeoutError,
    )
    import threading

    representative = family[0]
    family_name = representative.name.split("_SL")[0].split("_TP")[0][:50]

    strategy_dict = {
        "buy_conditions": representative.buy_conditions or [],
        "sell_conditions": representative.sell_conditions or [],
    }

    # Phase 1: prepare_data() — shared across all family members
    pe = PortfolioBacktestEngine(
        initial_capital=100000,
        max_positions=10,
        max_position_pct=30,
        slippage_pct=0.1,
    )

    t0 = time.time()
    precomputed = pe.prepare_data(strategy_dict, stock_data)
    prep_time = time.time() - t0

    if not precomputed.get("prepared"):
        logger.warning("  Family '%s': No prepared data, skipping %d strategies", family_name, len(family))
        return {"done": 0, "failed": len(family), "invalid": 0, "stda": 0}

    logger.info("  prepare_data: %.1fs, %d stocks, %d dates",
                prep_time, len(precomputed["prepared"]), len(precomputed["sorted_dates"]))

    # Phase 2: run_with_prepared() for each strategy
    stats = {"done": 0, "failed": 0, "invalid": 0, "stda": 0}

    for i, strat in enumerate(family):
        exit_config = strat.exit_config or {}

        try:
            cancel_event = threading.Event()
            timer = threading.Timer(600, cancel_event.set)  # 10 min timeout
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
            except (SignalExplosionError, BacktestTimeoutError) as e:
                logger.warning("  S%d %s: %s", strat.id, strat.name[:40], str(e)[:100])
                stats["invalid"] += 1
                if not dry_run:
                    strat.backtest_summary = {
                        "score": 0, "total_return_pct": 0, "max_drawdown_pct": 0,
                        "win_rate": 0, "total_trades": 0, "avg_hold_days": 0,
                        "avg_pnl_pct": 0, "regime_stats": {},
                    }
                    session.commit()
                continue
            finally:
                timer.cancel()

            if result.total_trades == 0:
                stats["invalid"] += 1
                if not dry_run:
                    strat.backtest_summary = {
                        "score": 0, "total_return_pct": 0, "max_drawdown_pct": 0,
                        "win_rate": 0, "total_trades": 0, "avg_hold_days": 0,
                        "avg_pnl_pct": 0, "regime_stats": {},
                    }
                    session.commit()
                continue

            score = compute_score(result)

            new_summary = {
                "score": score,
                "total_return_pct": round(result.total_return_pct, 2),
                "max_drawdown_pct": round(result.max_drawdown_pct, 2),
                "win_rate": round(result.win_rate, 2),
                "total_trades": result.total_trades,
                "avg_hold_days": round(result.avg_hold_days, 1),
                "avg_pnl_pct": round(result.avg_pnl_pct, 2),
                "regime_stats": result.regime_stats or {},
            }

            if not dry_run:
                strat.backtest_summary = new_summary
                if (i + 1) % 50 == 0:
                    session.commit()  # Batch commit every 50

            stats["done"] += 1

            # Check StdA+ criteria
            dd = abs(result.max_drawdown_pct)
            if (score >= 0.70 and result.total_return_pct > 20
                    and dd < 25 and result.total_trades >= 50):
                stats["stda"] += 1

        except Exception as e:
            logger.error("  S%d %s: ERROR %s", strat.id, strat.name[:40], str(e)[:200])
            stats["failed"] += 1

    if not dry_run:
        session.commit()

    return stats


def main():
    parser = argparse.ArgumentParser(description="Mass re-backtest all strategies with T+1 engine")
    parser.add_argument("--dry-run", action="store_true", help="Don't update DB, just measure")
    parser.add_argument("--family-id", type=int, help="Only run family N (0-indexed)")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Mass Re-Backtest: T+1 Engine")
    logger.info("=" * 60)

    session = get_db_session()

    # Date range: 3 years
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")
    logger.info("Period: %s → %s", start_date, end_date)

    # Step 1: Load stock data (once, shared)
    logger.info("\n[Step 1] Loading stock data...")
    t0 = time.time()
    stock_data = load_stock_data(session, start_date, end_date)
    logger.info("Stock data loaded in %.1fs", time.time() - t0)

    # Step 2: Load regime map (once, shared)
    logger.info("\n[Step 2] Loading regime map...")
    regime_map = load_regime_map(session, start_date, end_date)
    logger.info("Regime map: %d dates", len(regime_map) if regime_map else 0)

    # Step 3: Group strategies by family
    logger.info("\n[Step 3] Grouping strategies...")
    families = group_strategies(session)
    total_strategies = sum(len(f) for f in families)
    logger.info("Found %d families, %d total strategies", len(families), total_strategies)

    for i, family in enumerate(families):
        logger.info("  Family %d: %d strategies — %s", i, len(family), family[0].name[:60])

    # Step 4: Run backtests family by family
    logger.info("\n[Step 4] Running backtests...")
    overall_start = time.time()
    total_stats = {"done": 0, "failed": 0, "invalid": 0, "stda": 0}
    completed_strategies = 0

    families_to_run = [families[args.family_id]] if args.family_id is not None else families

    for fi, family in enumerate(families_to_run):
        family_idx = args.family_id if args.family_id is not None else fi
        family_name = family[0].name.split("_SL")[0].split("_TP")[0][:50]
        logger.info("\n── Family %d/%d: '%s' (%d strategies) ──",
                    family_idx, len(families), family_name, len(family))

        t0 = time.time()
        stats = run_family(family, stock_data, regime_map, session, dry_run=args.dry_run)
        elapsed = time.time() - t0

        for k in total_stats:
            total_stats[k] += stats[k]
        completed_strategies += len(family)

        logger.info("  Results: done=%d, invalid=%d, failed=%d, StdA+=%d (%.1fs, %.2fs/strategy)",
                    stats["done"], stats["invalid"], stats["failed"], stats["stda"],
                    elapsed, elapsed / len(family) if family else 0)

        # Progress estimate
        remaining = total_strategies - completed_strategies
        avg_time_per = (time.time() - overall_start) / completed_strategies if completed_strategies else 0
        eta_min = remaining * avg_time_per / 60
        logger.info("  Progress: %d/%d (%.0f%%), ETA: %.0f min",
                    completed_strategies, total_strategies,
                    completed_strategies / total_strategies * 100 if total_strategies else 0,
                    eta_min)

    total_elapsed = time.time() - overall_start

    # Step 5: Summary
    logger.info("\n" + "=" * 60)
    logger.info("MASS RE-BACKTEST COMPLETE")
    logger.info("=" * 60)
    logger.info("Total time: %.1f min (%.1f sec/strategy)",
                total_elapsed / 60, total_elapsed / total_strategies if total_strategies else 0)
    logger.info("Results: done=%d, invalid=%d, failed=%d",
                total_stats["done"], total_stats["invalid"], total_stats["failed"])
    logger.info("StdA+ (score>=0.70, ret>20%%, dd<25%%, trades>=50): %d", total_stats["stda"])
    logger.info("Dry run: %s", args.dry_run)

    # Save summary to file for memory sync
    summary = {
        "timestamp": datetime.now().isoformat(),
        "engine_version": "T+1 with slippage and limit prices",
        "period": f"{start_date} → {end_date}",
        "total_strategies": total_strategies,
        "families": len(families),
        "done": total_stats["done"],
        "invalid": total_stats["invalid"],
        "failed": total_stats["failed"],
        "stda_count": total_stats["stda"],
        "total_time_min": round(total_elapsed / 60, 1),
        "dry_run": args.dry_run,
    }
    with open("/tmp/mass_rebacktest_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logger.info("\nSummary saved to /tmp/mass_rebacktest_summary.json")

    session.close()


if __name__ == "__main__":
    main()
