#!/usr/bin/env python3
"""Full rebuild of daily_prices table with raw OHLCV + adj_factor from TDX.

Usage:
    # Full rebuild (all stocks from 2015-01-01)
    python3 scripts/rebuild_daily_prices.py --yes

    # Test with 5 stocks
    python3 scripts/rebuild_daily_prices.py --limit 5

    # Custom start date
    python3 scripts/rebuild_daily_prices.py --start-date 2020-01-01 --yes
"""

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Rebuild daily_prices from TDX")
    parser.add_argument("--limit", type=int, default=0, help="Limit to N stocks (0=all)")
    parser.add_argument("--start-date", default="2015-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    from api.models.base import SessionLocal, engine
    from api.models.stock import Stock, DailyPrice
    from api.services.tdx_collector import TdxCollector
    from sqlalchemy import text

    db = SessionLocal()

    # Get stock codes
    query = db.query(Stock.code).order_by(Stock.code)
    if args.limit > 0:
        query = query.limit(args.limit)
    codes = [r.code for r in query.all()]

    if not codes:
        logger.error("No stocks in database. Run stock list sync first.")
        db.close()
        return

    logger.info("Will rebuild daily_prices for %d stocks from %s", len(codes), args.start_date)

    # Confirmation
    if not args.yes:
        confirm = input(f"This will TRUNCATE daily_prices and rebuild {len(codes)} stocks. Continue? [y/N] ")
        if confirm.lower() != "y":
            logger.info("Aborted.")
            db.close()
            return

    # Truncate
    logger.info("Truncating daily_prices...")
    db.execute(text("TRUNCATE TABLE daily_prices"))
    db.commit()
    logger.info("daily_prices truncated.")

    # Rebuild
    tdx = TdxCollector()
    today = date.today().isoformat()
    start = args.start_date
    total_rows = 0
    failed = 0
    batch_objects = []
    BATCH_SIZE = 50

    t0 = time.time()

    for i, code in enumerate(codes):
        retries = 0
        df = None
        while retries < 3:
            try:
                df = tdx.fetch_daily_raw(code, start, today)
                break
            except Exception as e:
                retries += 1
                logger.warning("Retry %d/3 for %s: %s", retries, code, e)
                # Force reconnect by clearing cached IP
                tdx._best_ip = None
                tdx._ip_cache_time = 0.0
                time.sleep(1)

        if df is None or df.empty:
            failed += 1
            if (i + 1) % BATCH_SIZE == 0:
                logger.info(
                    "Progress: %d/%d stocks, %d rows, %d skipped, %.0fs elapsed",
                    i + 1, len(codes), total_rows, failed, time.time() - t0,
                )
            continue

        for _, row in df.iterrows():
            try:
                d_str = row["date"]
                trade_d = date.fromisoformat(d_str) if isinstance(d_str, str) else d_str
                batch_objects.append(DailyPrice(
                    stock_code=code,
                    trade_date=trade_d,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0)),
                    amount=0.0,
                    adj_factor=float(row.get("adj_factor", 1.0)),
                ))
            except Exception:
                continue

        total_rows += len(df)

        # Commit every BATCH_SIZE stocks
        if (i + 1) % BATCH_SIZE == 0:
            try:
                db.bulk_save_objects(batch_objects)
                db.commit()
            except Exception as e:
                logger.error("Batch commit failed at stock %d: %s", i + 1, e)
                db.rollback()
            batch_objects = []

            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(codes) - i - 1) / rate if rate > 0 else 0
            logger.info(
                "Progress: %d/%d stocks, %d rows, %d skipped, %.0fs elapsed, ETA %.0fs",
                i + 1, len(codes), total_rows, failed, elapsed, eta,
            )

    # Final batch
    if batch_objects:
        try:
            db.bulk_save_objects(batch_objects)
            db.commit()
        except Exception as e:
            logger.error("Final batch commit failed: %s", e)
            db.rollback()

    elapsed = time.time() - t0
    logger.info(
        "Rebuild complete: %d stocks, %d rows, %d skipped, %.0fs elapsed",
        len(codes), total_rows, failed, elapsed,
    )

    # VACUUM ANALYZE
    logger.info("Running VACUUM ANALYZE daily_prices...")
    try:
        # VACUUM cannot run inside a transaction; use raw connection
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(text("VACUUM ANALYZE daily_prices"))
        logger.info("VACUUM ANALYZE done.")
    except Exception as e:
        logger.warning("VACUUM ANALYZE failed (non-fatal): %s", e)

    db.close()


if __name__ == "__main__":
    main()
