"""Backfill profit_loss_ratio for active strategies missing PLR data.

Groups by skeleton for efficient prepare_data sharing.
Uses top-500 stocks (by data length) for speed — PLR is ratio-based so
a representative sample gives accurate results.
"""

import sys
import time
import logging
from collections import defaultdict

sys.path.insert(0, "/Users/allenqiang/stockagent")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

from api.models.base import get_db
from api.models.strategy import Strategy
from api.services.strategy_pool import _extract_skeleton
from api.services.data_collector import DataCollector
from src.backtest.portfolio_engine import PortfolioBacktestEngine

db = next(get_db())

# Find active strategies missing PLR
active = db.query(Strategy).filter(
    Strategy.archived_at.is_(None),
    Strategy.signal_fingerprint.isnot(None),
).all()

no_plr = [s for s in active if not (s.backtest_summary or {}).get("profit_loss_ratio")]
log.info("Active: %d, missing PLR: %d", len(active), len(no_plr))

if not no_plr:
    log.info("Nothing to backfill!")
    sys.exit(0)

# Group by skeleton for prepare_data sharing
by_skel = defaultdict(list)
for s in no_plr:
    skel = _extract_skeleton(s.name, s.buy_conditions, s.sell_conditions)
    by_skel[skel].append(s)

log.info("%d strategies -> %d skeletons", len(no_plr), len(by_skel))

# Load stock data — use top 500 stocks for speed
log.info("Loading stock data (top 500 stocks)...")
collector = DataCollector(db)
end_date = "2026-03-14"
start_date = "2024-01-01"
stock_codes = collector.get_stocks_with_data(min_rows=60)

# Load all, then keep top 500 by data length
all_stock_data = {}
for code in stock_codes:
    df = collector.get_daily_df(code, start_date, end_date, local_only=True)
    if df is not None and not df.empty and len(df) >= 60:
        all_stock_data[code] = df

# Sort by data length (more data = better represented) and take top 500
sorted_codes = sorted(all_stock_data.keys(), key=lambda c: len(all_stock_data[c]), reverse=True)
stock_data = {c: all_stock_data[c] for c in sorted_codes[:500]}
del all_stock_data
log.info("Using %d stocks (from %d total)", len(stock_data), len(sorted_codes))

filled = 0
failed = 0
t0 = time.time()

for i, (skel, strats) in enumerate(sorted(by_skel.items(), key=lambda x: -len(x[1]))):
    rep = strats[0]
    log.info("[%d/%d] Skeleton: %s (%d strats)", i + 1, len(by_skel), skel[:50], len(strats))

    pe = PortfolioBacktestEngine(
        initial_capital=100000,
        max_positions=10,
        max_position_pct=30,
    )

    strategy_dict = {
        "buy_conditions": rep.buy_conditions or [],
        "sell_conditions": rep.sell_conditions or [],
    }

    try:
        precomputed = pe.prepare_data(strategy_dict, stock_data)
        if not precomputed.get("prepared"):
            log.warning("  No prepared data, skipping")
            failed += len(strats)
            continue
    except Exception as e:
        log.warning("  prepare_data failed: %s", e)
        failed += len(strats)
        continue

    for s in strats:
        try:
            result = pe.run_with_prepared(
                strategy_name=s.name,
                exit_config=s.exit_config or {},
                precomputed=precomputed,
            )
            plr = result.profit_loss_ratio if result and result.profit_loss_ratio else 0.0

            bs = dict(s.backtest_summary or {})
            bs["profit_loss_ratio"] = round(plr, 4)
            s.backtest_summary = bs
            filled += 1
        except Exception as e:
            log.warning("  S%d failed: %s", s.id, e)
            failed += 1

    db.commit()
    elapsed = time.time() - t0
    rate = filled / elapsed if elapsed > 0 else 0
    eta = (len(no_plr) - filled) / rate if rate > 0 else 0
    log.info("  Progress: %d/%d (%.1f/s, ETA %.0fm), %d failed", filled, len(no_plr), rate, eta / 60, failed)

elapsed = time.time() - t0
log.info("=== COMPLETE: %d filled, %d failed in %.1fs (%.1fm) ===", filled, failed, elapsed, elapsed / 60)
