#!/usr/bin/env python3
"""Walk-forward scan for all active champion strategies.

Loads stock data ONCE, then runs walk-forward validation on each champion.
Outputs a ranked report with overfit ratio, consistency, and test-period metrics.

Usage:
    cd /Users/allenqiang/stockagent
    NO_PROXY=localhost,127.0.0.1 python scripts/walk_forward_scan.py [--limit N] [--train-years 2] [--test-months 6]
"""

import argparse
import json
import logging
import os
import sys
import time
import threading
from datetime import datetime

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


def load_champions(session, limit=None):
    """Load all active champion strategies, sorted by score desc."""
    from api.models.strategy import Strategy

    q = (
        session.query(Strategy)
        .filter(Strategy.enabled == True, Strategy.archived_at == None)
        .order_by(Strategy.id.desc())
    )
    strategies = q.all()

    if limit:
        strategies = strategies[:limit]

    logger.info("Loaded %d champion strategies", len(strategies))
    return strategies


def load_stock_data(session, start_date: str, end_date: str):
    """Load all stock data for the full period (shared across all strategies)."""
    from api.services.data_collector import DataCollector

    collector = DataCollector(session)
    stock_codes = collector.get_stocks_with_data(min_rows=60)
    logger.info("Loading stock data for %d stocks (%s ~ %s)...", len(stock_codes), start_date, end_date)

    stock_data = {}
    for i, code in enumerate(stock_codes):
        df = collector.get_daily_df(code, start_date, end_date, local_only=True)
        if df is not None and not df.empty and len(df) >= 60:
            stock_data[code] = df
        if (i + 1) % 500 == 0:
            logger.info("  Loaded %d/%d stocks...", i + 1, len(stock_codes))

    logger.info("Loaded %d stocks with valid data", len(stock_data))
    return stock_data


def load_index_data(session, start_date: str, end_date: str):
    """Load Shanghai Composite index data for benchmark."""
    try:
        from api.services.data_collector import DataCollector
        collector = DataCollector(session)
        df = collector.get_daily_df("000001.SH", start_date, end_date, local_only=True)
        if df is not None and not df.empty:
            logger.info("Loaded index data: %d rows", len(df))
            return df
    except Exception as e:
        logger.warning("Failed to load index data: %s", e)
    return None


def group_by_conditions(strategies):
    """Group strategies by buy+sell conditions (same signals = same family)."""
    import json as _json
    from collections import defaultdict

    families = defaultdict(list)
    for s in strategies:
        key = _json.dumps(s.buy_conditions or [], sort_keys=True) + "|||" + \
              _json.dumps(s.sell_conditions or [], sort_keys=True)
        families[key].append(s)

    return list(families.values())


def main():
    parser = argparse.ArgumentParser(description="Walk-forward scan for active strategies")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of strategies to scan")
    parser.add_argument("--train-years", type=float, default=2.0, help="Training window in years")
    parser.add_argument("--test-months", type=int, default=6, help="Test window in months")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path")
    args = parser.parse_args()

    session = get_db_session()

    # Load strategies
    champions = load_champions(session, limit=args.limit)
    if not champions:
        logger.error("No strategies found")
        return

    # Load stock data once (covers full 2020-2025 period)
    t0 = time.time()
    stock_data = load_stock_data(session, "2020-01-01", "2025-12-31")
    index_data = load_index_data(session, "2020-01-01", "2025-12-31")
    data_time = time.time() - t0
    logger.info("Data loading took %.1fs", data_time)

    # Group by conditions to share prepare_data()
    families = group_by_conditions(champions)
    logger.info("Grouped into %d condition families", len(families))

    from src.backtest.portfolio_engine import PortfolioBacktestEngine
    from src.backtest.walk_forward import run_walk_forward

    results = []
    strat_idx = 0
    total = len(champions)

    for fam_i, family in enumerate(families):
        rep = family[0]
        strategy_dict = {
            "name": rep.name,
            "buy_conditions": rep.buy_conditions or [],
            "sell_conditions": rep.sell_conditions or [],
            "exit_config": rep.exit_config or {},
        }

        # prepare_data once per family
        engine = PortfolioBacktestEngine()
        try:
            precomputed = engine.prepare_data(strategy_dict, stock_data)
        except Exception as e:
            logger.warning("Family %d prepare_data failed: %s", fam_i + 1, str(e)[:200])
            for strat in family:
                strat_idx += 1
                bs = strat.backtest_summary or {}
                results.append({
                    "id": strat.id, "name": strat.name[:80],
                    "score": bs.get("score", 0), "full_return": bs.get("total_return_pct", 0),
                    "status": "failed",
                })
            continue

        if not precomputed.get("prepared"):
            logger.warning("Family %d: no prepared data", fam_i + 1)
            for strat in family:
                strat_idx += 1
                bs = strat.backtest_summary or {}
                results.append({
                    "id": strat.id, "name": strat.name[:80],
                    "score": bs.get("score", 0), "full_return": bs.get("total_return_pct", 0),
                    "status": "failed",
                })
            continue

        logger.info("Family %d/%d: %d stocks prepared, %d strategies",
                    fam_i + 1, len(families),
                    len(precomputed["prepared"]), len(family))

        # Walk-forward each strategy in this family
        for strat in family:
            strat_idx += 1
            bs = strat.backtest_summary or {}
            score = bs.get("score", 0)
            ret = bs.get("total_return_pct", 0)

            logger.info("[%d/%d] S%d score=%.4f ret=%.1f%%  %s",
                        strat_idx, total, strat.id, score, ret, strat.name[:60])

            t1 = time.time()
            try:
                wf_strategy = {
                    "name": strat.name,
                    "buy_conditions": strat.buy_conditions or [],
                    "sell_conditions": strat.sell_conditions or [],
                    "exit_config": strat.exit_config or {},
                }
                wf = run_walk_forward(
                    strategy=wf_strategy,
                    stock_data=stock_data,
                    start_date="2020-01-01",
                    end_date="2025-12-31",
                    train_years=args.train_years,
                    test_months=args.test_months,
                    step_months=args.test_months,
                    precomputed=precomputed,
                )
            except Exception as e:
                logger.error("  Walk-forward failed: %s", str(e)[:200])
                wf = None
            elapsed = time.time() - t1

            if wf is None:
                logger.warning("  → FAILED (%.1fs)", elapsed)
                results.append({
                    "id": strat.id, "name": strat.name[:80],
                    "score": score, "full_return": ret, "status": "failed",
                })
                continue

            logger.info(
                "  → %d rounds, test_avg_ret=%.1f%%, consistency=%.0f%%, overfit=%.1fx (%.1fs)",
                wf.total_rounds, wf.test_avg_return, wf.consistency_pct, wf.overfit_ratio, elapsed,
            )

            results.append({
                "id": strat.id,
                "name": strat.name[:80],
                "score": score,
                "full_return": ret,
                "status": "ok",
                "wf_rounds": wf.total_rounds,
                "test_avg_return": wf.test_avg_return,
                "test_avg_win_rate": wf.test_avg_win_rate,
                "test_avg_sharpe": wf.test_avg_sharpe,
                "test_avg_max_dd": wf.test_avg_max_dd,
                "test_total_trades": wf.test_total_trades,
                "train_avg_return": wf.train_avg_return,
                "overfit_ratio": wf.overfit_ratio,
                "profitable_rounds": wf.profitable_rounds,
                "consistency_pct": wf.consistency_pct,
                "elapsed_s": round(elapsed, 1),
            })

    # Sort by consistency desc, then test_avg_return desc
    ok_results = [r for r in results if r["status"] == "ok"]
    ok_results.sort(key=lambda r: (r["consistency_pct"], r["test_avg_return"]), reverse=True)
    failed = [r for r in results if r["status"] != "ok"]

    # Print report
    print("\n" + "=" * 120)
    print(f"Walk-Forward Scan Report — {len(ok_results)} strategies, "
          f"train={args.train_years}yr test={args.test_months}mo")
    print("=" * 120)

    print(f"\n{'ID':>6} {'Score':>6} {'FullRet':>8} {'TestRet':>8} {'TestWR':>7} "
          f"{'TestDD':>7} {'Sharpe':>7} {'Overfit':>8} {'Consist':>8} {'Rounds':>7} {'Trades':>7}")
    print("-" * 120)

    for r in ok_results:
        flag = ""
        if r["overfit_ratio"] > 3:
            flag = " ⚠ OVERFIT"
        elif r["consistency_pct"] < 50:
            flag = " ⚠ UNSTABLE"
        elif r["consistency_pct"] >= 80 and r["overfit_ratio"] < 2:
            flag = " ★ ROBUST"

        print(f"{r['id']:>6} {r['score']:>6.4f} {r['full_return']:>7.1f}% "
              f"{r['test_avg_return']:>7.1f}% {r['test_avg_win_rate']:>6.1f}% "
              f"{r['test_avg_max_dd']:>6.1f}% {r['test_avg_sharpe']:>7.2f} "
              f"{r['overfit_ratio']:>7.1f}x {r['consistency_pct']:>7.1f}% "
              f"{r['wf_rounds']:>7} {r['test_total_trades']:>7}{flag}")

    if failed:
        print(f"\nFailed: {len(failed)} strategies")

    # Summary
    if ok_results:
        robust = [r for r in ok_results if r["consistency_pct"] >= 80 and r["overfit_ratio"] < 2]
        overfit = [r for r in ok_results if r["overfit_ratio"] > 3]
        unstable = [r for r in ok_results if r["consistency_pct"] < 50]

        print(f"\n{'Summary':=^120}")
        print(f"  Total scanned:    {len(ok_results)}")
        print(f"  ★ Robust:         {len(robust)} (consistency>=80%, overfit<2x)")
        print(f"  ⚠ Overfit:        {len(overfit)} (overfit>3x)")
        print(f"  ⚠ Unstable:       {len(unstable)} (consistency<50%)")
        print(f"  Avg test return:  {sum(r['test_avg_return'] for r in ok_results) / len(ok_results):.1f}%")
        print(f"  Avg consistency:  {sum(r['consistency_pct'] for r in ok_results) / len(ok_results):.1f}%")
        print(f"  Avg overfit:      {sum(r['overfit_ratio'] for r in ok_results) / len(ok_results):.1f}x")

    # Save JSON
    output_path = args.output or f"data/walk_forward_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({"results": ok_results + failed, "args": vars(args)}, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {output_path}")

    session.close()


if __name__ == "__main__":
    main()
