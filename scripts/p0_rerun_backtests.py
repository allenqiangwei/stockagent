"""Re-run backtests for P0-affected strategies (extended indicators not collected).

Identifies zero-trade strategies that used extended indicators (CCI, MFI, BOLL, etc.),
re-runs their backtests with the fixed collect_indicator_params(), and reports results.
"""

import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

# Setup path
sys.path.insert(0, "/Users/allenqiang/stockagent")

from sqlalchemy.orm import Session
from api.models.base import SessionLocal
from api.models.ai_lab import ExperimentStrategy
from api.services.data_collector import DataCollector
from api.services.ai_lab_engine import _compute_score
from api.config import get_settings
from src.backtest.portfolio_engine import PortfolioBacktestEngine

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

# Extended indicator fields
EXTENDED_FIELDS = {
    "CCI", "MFI", "WR", "ROC", "TRIX", "DPO", "STOCHRSI_K", "STOCHRSI_D",
    "VWAP", "CMF", "BOLL_upper", "BOLL_middle", "BOLL_lower",
}


def find_p0_affected(db: Session) -> list[dict]:
    """Find zero-trade strategies that used extended indicators."""
    rows = db.query(ExperimentStrategy).filter(
        ExperimentStrategy.status == "invalid",
        ExperimentStrategy.error_message.like("%零交易%"),
    ).all()

    affected = []
    for r in rows:
        buy = r.buy_conditions or []
        sell = r.sell_conditions or []
        all_conds = buy + sell

        used_ext = set()
        for c in all_conds:
            f = c.get("field", "")
            cf = c.get("compare_field", "")
            if f in EXTENDED_FIELDS:
                used_ext.add(f)
            if cf in EXTENDED_FIELDS:
                used_ext.add(cf)

        if used_ext:
            affected.append({
                "id": r.id,
                "exp_id": r.experiment_id,
                "name": r.name,
                "ext_indicators": sorted(used_ext),
                "strategy_obj": r,
            })

    return affected


def run_backtest_update(strat_obj, stock_data: dict, regime_map: dict | None):
    """Run portfolio backtest for a single strategy and update its fields."""
    strategy_dict = {
        "name": strat_obj.name,
        "buy_conditions": strat_obj.buy_conditions or [],
        "sell_conditions": strat_obj.sell_conditions or [],
        "exit_config": strat_obj.exit_config or {},
    }

    engine = PortfolioBacktestEngine(
        initial_capital=100000.0,
        max_positions=10,
        max_position_pct=30.0,
    )
    result = engine.run(strategy_dict, stock_data, regime_map=regime_map)

    # Update strategy record
    strat_obj.total_trades = result.total_trades
    strat_obj.win_rate = result.win_rate
    strat_obj.total_return_pct = result.total_return_pct
    strat_obj.max_drawdown_pct = result.max_drawdown_pct
    strat_obj.avg_hold_days = result.avg_hold_days
    strat_obj.avg_pnl_pct = result.avg_pnl_pct
    strat_obj.regime_stats = result.regime_stats if result.regime_stats else None

    if result.total_trades == 0:
        strat_obj.score = 0.0
        strat_obj.status = "invalid"
        strat_obj.error_message = "零交易: 买入条件在回测期间从未满足(P0修复后)"
    else:
        lab_cfg = get_settings().ai_lab
        weights = {
            "weight_return": lab_cfg.weight_return,
            "weight_drawdown": lab_cfg.weight_drawdown,
            "weight_sharpe": lab_cfg.weight_sharpe,
            "weight_plr": lab_cfg.weight_plr,
        }
        strat_obj.score = round(_compute_score(result, weights), 4)
        strat_obj.status = "done"
        strat_obj.error_message = ""

    return result


def main():
    db = SessionLocal()
    collector = DataCollector(db)

    # Step 1: Find affected strategies
    affected = find_p0_affected(db)
    print(f"{'=' * 60}")
    print(f"P0 修复回测 — {len(affected)} 个受影响的策略")
    print(f"{'=' * 60}")

    if not affected:
        print("没有受影响的策略")
        return

    # Step 2: Load stock data (shared across all strategies)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")

    print(f"\n加载股票数据 ({start_date} ~ {end_date})...")
    stock_codes = collector.get_stocks_with_data(min_rows=60)
    stock_data = {}
    for code in stock_codes:
        df = collector.get_daily_df(code, start_date, end_date, local_only=True)
        if df is not None and not df.empty and len(df) >= 60:
            stock_data[code] = df
    print(f"OK 加载 {len(stock_data)} 只股票")

    # Step 3: Load regime map
    regime_map = None
    try:
        from api.services.regime_service import ensure_regimes, get_regime_map
        ensure_regimes(db, start_date, end_date)
        regime_map = get_regime_map(db, start_date, end_date)
        print(f"OK 加载 {len(regime_map)} 天的市场阶段数据")
    except Exception as e:
        print(f"WARN 市场阶段加载失败: {e}")

    # Step 4: Re-run backtests
    results = {
        "fixed": [],      # Was zero-trade, now has trades
        "still_zero": [], # Still zero-trade after fix
        "errors": [],     # Backtest errors
    }
    total = len(affected)
    t0 = time.time()

    for idx, info in enumerate(affected, 1):
        strat = info["strategy_obj"]
        name = info["name"]
        ext = ", ".join(info["ext_indicators"])

        try:
            result = run_backtest_update(strat, stock_data, regime_map)

            if result.total_trades > 0:
                results["fixed"].append({
                    "id": strat.id,
                    "name": name,
                    "ext": ext,
                    "trades": result.total_trades,
                    "return_pct": result.total_return_pct,
                    "drawdown": result.max_drawdown_pct,
                    "score": strat.score,
                    "win_rate": result.win_rate,
                })
                detail = f"收益{result.total_return_pct:+.1f}% 回撤{result.max_drawdown_pct:.1f}% {result.total_trades}笔 得分{strat.score:.2f}"
                print(f"  OK [{idx}/{total}] {name} ({ext}) -> {detail}")
            else:
                results["still_zero"].append({
                    "id": strat.id,
                    "name": name,
                    "ext": ext,
                })
                print(f"  -- [{idx}/{total}] {name} ({ext}) -> 仍零交易")

        except Exception as e:
            results["errors"].append({
                "id": strat.id,
                "name": name,
                "error": str(e),
            })
            strat.status = "invalid"
            strat.error_message = f"回测错误: {e}"
            print(f"  ERR [{idx}/{total}] {name} -> 错误: {e}")

        # Commit every 10 strategies to avoid large transactions
        if idx % 10 == 0:
            db.commit()
            elapsed = time.time() - t0
            rate = idx / elapsed
            eta = (total - idx) / rate if rate > 0 else 0
            print(f"  PROGRESS {idx}/{total} ({elapsed:.0f}s, ETA {eta:.0f}s)")

    db.commit()
    elapsed = time.time() - t0

    # Step 5: Summary
    fixed = results["fixed"]
    still_zero = results["still_zero"]
    errors = results["errors"]

    print(f"\n{'=' * 60}")
    print(f"P0 修复回测结果")
    print(f"{'=' * 60}")
    print(f"总计: {total} 个策略")
    print(f"  修复成功 (有交易): {len(fixed)} ({len(fixed)/total*100:.1f}%)")
    print(f"  仍零交易: {len(still_zero)} ({len(still_zero)/total*100:.1f}%)")
    print(f"  错误: {len(errors)} ({len(errors)/total*100:.1f}%)")
    print(f"  耗时: {elapsed:.0f}s ({elapsed/total:.1f}s/策略)")

    if fixed:
        # Profitable analysis
        profitable = [s for s in fixed if s["return_pct"] > 0]
        print(f"\n盈利策略: {len(profitable)}/{len(fixed)} ({len(profitable)/len(fixed)*100:.1f}%)")

        # Sort by score
        fixed_sorted = sorted(fixed, key=lambda x: x["score"], reverse=True)
        print(f"\n得分 Top 20:")
        for i, s in enumerate(fixed_sorted[:20], 1):
            print(
                f"  {i:2d}. {s['name']:<40s} "
                f"得分{s['score']:.2f} "
                f"收益{s['return_pct']:+7.1f}% "
                f"回撤{s['drawdown']:5.1f}% "
                f"胜率{s['win_rate']:.1f}% "
                f"{s['trades']}笔"
            )

        # Return > 30%
        high_return = [s for s in fixed if s["return_pct"] > 30]
        if high_return:
            print(f"\n收益 > 30% 的策略 ({len(high_return)} 个):")
            for s in sorted(high_return, key=lambda x: x["return_pct"], reverse=True):
                print(f"  {s['name']}: {s['return_pct']:+.1f}% (ext: {s['ext']})")

        # Return > 10%
        good_return = [s for s in fixed if s["return_pct"] > 10]
        if good_return:
            print(f"\n收益 > 10% 的策略 ({len(good_return)} 个):")
            for s in sorted(good_return, key=lambda x: x["return_pct"], reverse=True):
                print(f"  {s['name']}: {s['return_pct']:+.1f}% (score={s['score']:.2f}, ext: {s['ext']})")

        # Extended indicator performance
        ext_perf = defaultdict(lambda: {"count": 0, "profitable": 0, "returns": []})
        for s in fixed:
            for ind in s["ext"].split(", "):
                ext_perf[ind]["count"] += 1
                ext_perf[ind]["returns"].append(s["return_pct"])
                if s["return_pct"] > 0:
                    ext_perf[ind]["profitable"] += 1

        print(f"\n各扩展指标表现:")
        print(f"  {'指标':<15s} {'策略数':>5s} {'盈利率':>7s} {'平均收益':>8s} {'最佳收益':>8s}")
        for ind, perf in sorted(ext_perf.items(), key=lambda x: -x[1]["count"]):
            avg_ret = sum(perf["returns"]) / len(perf["returns"])
            max_ret = max(perf["returns"])
            prof_rate = perf["profitable"] / perf["count"] * 100
            print(
                f"  {ind:<15s} {perf['count']:>5d} {prof_rate:>6.1f}% "
                f"{avg_ret:>+7.1f}% {max_ret:>+7.1f}%"
            )

    # Save results
    output = {
        "timestamp": datetime.now().isoformat(),
        "total": total,
        "fixed_count": len(fixed),
        "still_zero_count": len(still_zero),
        "error_count": len(errors),
        "elapsed_seconds": round(elapsed, 1),
        "fixed": fixed,
        "still_zero": still_zero,
        "errors": errors,
    }
    out_path = "/Users/allenqiang/stockagent/data/p0_rerun_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nOK 结果已保存到 {out_path}")

    db.close()


if __name__ == "__main__":
    main()
