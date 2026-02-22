"""Signal scheduler — runs signal generation daily at a configured time.

Daemon thread checks every 30 seconds whether the scheduled time has arrived.
Reads schedule from config/config.yaml (signals.auto_refresh_hour/minute).
"""

import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

from api.models.base import SessionLocal
from api.services.signal_engine import SignalEngine

logger = logging.getLogger(__name__)


class SignalScheduler:
    """Background scheduler that generates signals daily."""

    def __init__(self, refresh_hour: int = 19, refresh_minute: int = 0):
        self.refresh_hour = refresh_hour
        self.refresh_minute = refresh_minute
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_run_date: Optional[str] = None
        self._is_refreshing = False
        self._lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Signal scheduler started — daily at %02d:%02d",
            self.refresh_hour,
            self.refresh_minute,
        )

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Signal scheduler stopped.")

    # ── Schedule helpers ──────────────────────────────

    def get_next_run_time(self) -> str:
        """Return next scheduled run time as 'YYYY-MM-DD HH:MM'."""
        now = datetime.now()
        target = now.replace(
            hour=self.refresh_hour,
            minute=self.refresh_minute,
            second=0,
            microsecond=0,
        )
        if now >= target:
            target += timedelta(days=1)
        return target.strftime("%Y-%m-%d %H:%M")

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "is_refreshing": self._is_refreshing,
            "last_run_date": self._last_run_date,
            "next_run_time": self.get_next_run_time(),
            "refresh_hour": self.refresh_hour,
            "refresh_minute": self.refresh_minute,
        }

    # ── Main loop ─────────────────────────────────────

    def _run_loop(self):
        while self._running:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            should_run = (
                now.hour > self.refresh_hour
                or (now.hour == self.refresh_hour and now.minute >= self.refresh_minute)
            )

            if should_run and self._last_run_date != today and not self._is_refreshing:
                logger.info("Scheduled signal generation triggered for %s", today)
                self._do_refresh(today)

            # Check every 30 seconds
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)

    def _do_refresh(self, trade_date: str):
        with self._lock:
            if self._is_refreshing:
                return
            self._is_refreshing = True

        try:
            db = SessionLocal()
            try:
                # Step 0: Execute pending trade plans (runs on all days)
                try:
                    from api.services.bot_trading_engine import execute_pending_plans
                    plan_results = execute_pending_plans(db, trade_date)
                    if plan_results:
                        logger.info("Executed %d trade plans for %s", len(plan_results), trade_date)
                except Exception as e:
                    logger.error("Trade plan execution failed (non-fatal): %s", e)
                    try:
                        db.rollback()
                    except Exception:
                        pass

                # Step 0: Check if today is a trading day — skip heavy work if not
                is_trading_day = True
                try:
                    from api.services.data_collector import DataCollector
                    collector = DataCollector(db)
                    trading_dates = collector.get_trading_dates(trade_date, trade_date)
                    if not trading_dates or trade_date not in trading_dates:
                        is_trading_day = False
                        logger.info("Scheduler: %s is not a trading day, skipping data sync & signals", trade_date)
                except Exception as e:
                    logger.warning("Trading day check failed (assuming trading day): %s", e)

                if is_trading_day:
                    # Step 0b: Data integrity check
                    try:
                        if not collector:
                            from api.services.data_collector import DataCollector
                            collector = DataCollector(db)
                        collector.repair_daily_gaps(trade_date, trade_date)
                    except Exception as e:
                        logger.warning("Signal scheduler gap repair failed (non-fatal): %s", e)

                    # Step 1: Update daily prices for all tracked stocks
                    self._sync_daily_prices(db, trade_date)

                    # Step 2: Generate signals
                    engine = SignalEngine(db)
                    for _ in engine.generate_signals_stream(trade_date):
                        pass
                    logger.info("Scheduled signal generation completed for %s", trade_date)
                else:
                    logger.info("Skipped data sync & signal generation (non-trading day)")

                self._last_run_date = trade_date

                # Step 3: Run AI daily analysis (runs on both trading and non-trading days)
                self._run_ai_analysis(trade_date, db)
            finally:
                db.close()
        except Exception as e:
            logger.error("Scheduled signal generation failed: %s", e)
        finally:
            self._is_refreshing = False

    def _run_ai_analysis(self, trade_date: str, db):
        """Run Claude AI daily analysis after signal generation (non-fatal)."""
        try:
            from api.services.claude_runner import run_daily_analysis
            from api.models.ai_analyst import AIReport

            logger.info("Running AI daily analysis for %s...", trade_date)
            report = run_daily_analysis(trade_date)
            if report is None:
                logger.warning("AI daily analysis returned no result for %s", trade_date)
                return

            ai_report = AIReport(
                report_date=trade_date,
                report_type=report.get("report_type", "daily"),
                market_regime=report.get("market_regime"),
                market_regime_confidence=report.get("market_regime_confidence"),
                recommendations=report.get("recommendations"),
                strategy_actions=report.get("strategy_actions"),
                thinking_process=report.get("thinking_process", ""),
                summary=report.get("summary", ""),
            )
            db.add(ai_report)
            db.commit()
            logger.info("AI daily analysis saved for %s", trade_date)

            # Create trade plans from recommendations
            recs = report.get("recommendations")
            if recs:
                try:
                    from api.services.bot_trading_engine import create_trade_plans
                    plan_results = create_trade_plans(db, ai_report.id, trade_date, recs)
                    logger.info("Created %d trade plans from AI analysis", len(plan_results))
                except Exception as e:
                    logger.warning("Trade plan creation failed (non-fatal): %s", e)
        except Exception as e:
            logger.error("AI daily analysis failed (non-fatal): %s", e)
            try:
                db.rollback()
            except Exception:
                pass

    def _sync_daily_prices(self, db, trade_date: str):
        """Fetch latest daily prices for all stocks with existing data before generating signals."""
        from api.services.data_collector import DataCollector

        collector = DataCollector(db)
        codes = collector.get_stocks_with_data(min_rows=60)
        if not codes:
            logger.warning("No stocks with sufficient data to sync")
            return

        logger.info("Syncing daily prices for %d stocks before signal generation...", len(codes))
        updated = 0
        errors = 0
        for code in codes:
            try:
                df = collector.get_daily_df(code, trade_date, trade_date, local_only=False)
                if df is not None and not df.empty:
                    updated += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    logger.debug("Price sync failed for %s: %s", code, e)

            # Rate limit to avoid API throttling
            if updated % 50 == 0 and updated > 0:
                time.sleep(1)

        logger.info("Daily price sync done: %d updated, %d errors", updated, errors)


# ── Global singleton ──────────────────────────────

_scheduler: Optional[SignalScheduler] = None


def get_signal_scheduler() -> SignalScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        hour, minute = 19, 0
        try:
            from pathlib import Path
            import yaml

            config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                signals_cfg = cfg.get("signals", {})
                hour = signals_cfg.get("auto_refresh_hour", 19)
                minute = signals_cfg.get("auto_refresh_minute", 0)
        except Exception:
            pass

        _scheduler = SignalScheduler(refresh_hour=hour, refresh_minute=minute)
    return _scheduler


def start_signal_scheduler() -> SignalScheduler:
    """Start the scheduler (idempotent)."""
    svc = get_signal_scheduler()
    if not svc._running:
        svc.start()
    return svc


def stop_signal_scheduler():
    """Stop the scheduler if running."""
    global _scheduler
    if _scheduler and _scheduler._running:
        _scheduler.stop()
