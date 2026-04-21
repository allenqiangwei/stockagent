"""Data sync scheduler — syncs daily prices and executes trade plans at a configured time.

Daemon thread checks every 30 seconds whether the scheduled time has arrived.
Reads schedule from config/config.yaml (signals.auto_refresh_hour/minute).
"""

import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

from api.models.base import SessionLocal

logger = logging.getLogger(__name__)


class SignalScheduler:
    """Background scheduler that syncs daily data and executes trade plans."""

    def __init__(self, refresh_hour: int = 15, refresh_minute: int = 30):
        self.refresh_hour = refresh_hour
        self.refresh_minute = refresh_minute
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_run_date: Optional[str] = None
        self._is_refreshing = False
        self._sync_total: int = 0
        self._sync_done: int = 0
        self._sync_step: str = ""  # current step label
        self._lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Data sync scheduler started — daily at %02d:%02d",
            self.refresh_hour,
            self.refresh_minute,
        )

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Data sync scheduler stopped.")

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

    def get_latest_data_date(self) -> Optional[str]:
        """Query the latest trade_date from daily_prices table."""
        try:
            db = SessionLocal()
            try:
                from sqlalchemy import func
                from api.models.stock import DailyPrice
                result = db.query(func.max(DailyPrice.trade_date)).scalar()
                if result:
                    return result.isoformat() if hasattr(result, 'isoformat') else str(result)
            finally:
                db.close()
        except Exception as e:
            logger.debug("Failed to query latest data date: %s", e)
        return None

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "is_refreshing": self._is_refreshing,
            "last_run_date": self._last_run_date,
            "next_run_time": self.get_next_run_time(),
            "refresh_hour": self.refresh_hour,
            "refresh_minute": self.refresh_minute,
            "latest_data_date": self.get_latest_data_date(),
            "sync_total": self._sync_total,
            "sync_done": self._sync_done,
            "sync_step": self._sync_step,
        }

    # ── Main loop ─────────────────────────────────────

    def _run_loop(self):
        # On startup, train confidence model from historical data
        try:
            from api.services.confidence_scorer import train_confidence_model
            db = SessionLocal()
            try:
                cal = train_confidence_model(db)
                logger.info("Confidence model startup training: %s", cal.get("status"))
            finally:
                db.close()
        except Exception as e:
            logger.warning("Confidence model startup training failed: %s", e)

        # NOTE: never skip — even if daily_prices exist, the full pipeline
        # (signals, trade plans, beta/gamma scoring) may not have run.
        # _last_run_date stays None so the scheduler always fires after refresh_hour.

        while self._running:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            should_run = (
                now.hour > self.refresh_hour
                or (now.hour == self.refresh_hour and now.minute >= self.refresh_minute)
            )

            if should_run and self._last_run_date != today and not self._is_refreshing:
                logger.info("Scheduled data sync triggered for %s", today)
                self._do_refresh(today)

            # 20:00 补录 daily_basic（TuShare 数据延迟，15:30 时往往还没出）
            if now.hour == 20 and now.minute < 1 and not self._is_refreshing:
                self._backfill_daily_basic(today)

            # Sunday 03:00: full adj_factor recompute (weekly)
            if now.weekday() == 6 and now.hour == 3 and now.minute < 1 and not self._is_refreshing:
                self._recompute_all_adj_factors()

            # Check every 30 seconds
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)

    def _backfill_daily_basic(self, trade_date: str):
        """Backfill daily_basic at 20:00 if the 15:30 sync missed it (TuShare delay)."""
        try:
            from api.models.stock import DailyBasic
            from datetime import date as _date
            db = SessionLocal()
            try:
                exists = db.query(DailyBasic).filter(
                    DailyBasic.trade_date == _date.fromisoformat(trade_date)
                ).limit(1).count()
                if exists:
                    return  # Already have data, skip
                from api.services.data_collector import DataCollector
                collector = DataCollector(db)
                result = collector.get_daily_basic_df(trade_date)
                if result is not None and not result.empty:
                    logger.info("Backfilled daily_basic for %s: %d stocks", trade_date, len(result))
                else:
                    logger.info("Daily basic backfill: no data available yet for %s", trade_date)
            finally:
                db.close()
        except Exception as e:
            logger.warning("Daily basic backfill failed (non-fatal): %s", e)

    def _recompute_all_adj_factors(self):
        """Weekly full adj_factor recompute for all stocks."""
        try:
            from api.services.data_collector import DataCollector
            db = SessionLocal()
            try:
                collector = DataCollector(db)
                updated = collector.recompute_adj_factors(None)
                logger.info("Weekly adj_factor recompute: %d rows updated", updated)
            finally:
                db.close()
        except Exception as e:
            logger.warning("Weekly adj_factor recompute failed: %s", e)

    def _do_refresh(self, trade_date: str):
        with self._lock:
            if self._is_refreshing:
                return
            self._is_refreshing = True

        self._sync_total = 0
        self._sync_done = 0
        self._sync_step = "检查交易日"

        # Create a job for tracking
        from api.services.job_manager import get_job_manager
        jm = get_job_manager()
        job_id = jm.create("data_sync", f"Daily sync {trade_date}", triggered_by="scheduler")
        jm.start(job_id)

        try:
            db = SessionLocal()
            try:
                # Step 0: Check if today is a trading day
                is_trading_day = True
                collector = None
                try:
                    from api.services.data_collector import DataCollector
                    collector = DataCollector(db)
                    trading_dates = collector.get_trading_dates(trade_date, trade_date)
                    if not trading_dates or trade_date not in trading_dates:
                        is_trading_day = False
                        logger.info("Scheduler: %s is not a trading day, skipping", trade_date)
                except Exception as e:
                    logger.warning("Trading day check failed (assuming trading day): %s", e)

                if is_trading_day:
                    # Step 0b: Data integrity check
                    self._sync_step = "数据完整性检查"
                    jm.update_progress(job_id, 10, "数据完整性检查")
                    try:
                        if not collector:
                            from api.services.data_collector import DataCollector
                            collector = DataCollector(db)
                        collector.repair_daily_gaps(trade_date, trade_date)
                    except Exception as e:
                        logger.warning("Gap repair failed (non-fatal): %s", e)

                    # Step 1: Sync daily prices (batch: 1 API call for entire market)
                    self._sync_step = "批量同步日线数据"
                    jm.update_progress(job_id, 25, "批量同步日线数据")
                    self._sync_daily_prices(db, trade_date)

                    # Step 1b: Sync daily_basic (PE/PB/turnover for beta scoring)
                    try:
                        if not collector:
                            from api.services.data_collector import DataCollector
                            collector = DataCollector(db)
                        collector.get_daily_basic_df(trade_date)
                        logger.info("Daily basic synced for %s", trade_date)
                    except Exception as e:
                        logger.warning("Daily basic sync failed (non-fatal): %s", e)

                    # Step 2: Execute pending trade plans (needs today's OHLCV)
                    self._sync_step = "执行交易计划"
                    jm.update_progress(job_id, 50, "执行交易计划")
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

                    # Step 3: Monitor exit conditions (SL/TP/MHD)
                    self._sync_step = "监控退出条件"
                    jm.update_progress(job_id, 70, "监控退出条件")
                    try:
                        from api.services.bot_trading_engine import monitor_exit_conditions
                        exit_results = monitor_exit_conditions(db, trade_date)
                        if exit_results:
                            logger.info("Exit monitor: %d actions for %s", len(exit_results), trade_date)
                    except Exception as e:
                        logger.error("Exit monitoring failed (non-fatal): %s", e)
                        try:
                            db.rollback()
                        except Exception:
                            pass

                    # Step 3b: Strategy pool health check
                    self._sync_step = "策略池检查"
                    jm.update_progress(job_id, 75, "策略池健康检查")
                    try:
                        from api.services.strategy_pool import StrategyPoolManager
                        pool_mgr = StrategyPoolManager(db)
                        health = pool_mgr.daily_health_check()
                        logger.info(
                            "Pool health: %d active, %d families, %d oversized",
                            health["active_strategies"],
                            health["family_count"],
                            health["oversized_families"],
                        )
                    except Exception as e:
                        logger.warning("Pool health check failed (non-fatal): %s", e)

                    # Step 3b: Champion decay check (after rebalance, before signal gen)
                    self._sync_step = "策略衰减检查"
                    jm.update_progress(job_id, 77, "策略衰减检查")
                    try:
                        from api.services.strategy_pool import StrategyPoolManager as _SPM
                        decay_mgr = _SPM(db)
                        decay_result = decay_mgr.check_champion_decay()
                        if decay_result:
                            logger.info("Decay check: %d champions demoted", len(decay_result))
                    except Exception as e:
                        logger.warning("Decay check failed (non-fatal): %s", e)

                    # Step 4: Generate trading signals (full market scan)
                    self._sync_step = "生成交易信号"
                    jm.update_progress(job_id, 80, "生成交易信号")
                    try:
                        import json as _json
                        from api.services.signal_engine import SignalEngine
                        engine = SignalEngine(db)
                        # Consume the streaming generator to run full scan
                        generated = 0
                        for event_str in engine.generate_signals_stream(trade_date):
                            # Parse SSE: "data: {...}\n\n"
                            line = event_str.strip()
                            if line.startswith("data: "):
                                line = line[6:]
                            try:
                                payload = _json.loads(line)
                            except (ValueError, TypeError):
                                continue
                            evt_type = payload.get("type")
                            if evt_type == "start":
                                self._sync_total = payload.get("total", 0)
                                self._sync_done = 0
                            elif evt_type == "progress":
                                self._sync_done = payload.get("current", 0)
                                self._sync_step = f"生成交易信号 {self._sync_done}/{self._sync_total}"
                                # Update job progress: map signal scan 0-100% to job 80-95%
                                pct = payload.get("pct", 0)
                                job_pct = 80 + int(pct * 0.15)
                                if self._sync_done % 500 == 0:
                                    jm.update_progress(job_id, job_pct, f"生成信号 {self._sync_done}/{self._sync_total}")
                            elif evt_type == "done":
                                generated = payload.get("total_generated", 0)
                        logger.info("Signal generation done for %s: %d signals", trade_date, generated)
                    except Exception as e:
                        logger.error("Signal generation failed (non-fatal): %s", e)

                    # Step 4b: Match news to individual stocks
                    self._sync_step = "新闻个股关联"
                    jm.update_progress(job_id, 82, "新闻个股关联")
                    try:
                        from api.services.news_stock_matcher import match_news_to_stocks, align_news_prices
                        match_stats = match_news_to_stocks(db, lookback_hours=48)
                        aligned = align_news_prices(db, trade_date)
                        logger.info("News-stock matching: %d linked, %d aligned", match_stats.get("linked", 0), aligned)
                    except Exception as e:
                        logger.warning("News-stock matching failed (non-fatal): %s", e)

                    # Step 5: Track daily holdings for Beta Overlay
                    jm.update_progress(job_id, 85, "Beta每日追踪")
                    try:
                        from api.services.beta_tracker import track_daily_holdings
                        tracked = track_daily_holdings(db, trade_date)
                        if tracked:
                            logger.info("Beta daily tracking: %d holdings tracked", tracked)
                    except Exception as e:
                        logger.warning("Beta daily tracking failed (non-fatal): %s", e)

                    # Step 5c: Retrain Beta ML model (daily rolling)
                    jm.update_progress(job_id, 88, "Beta ML训练")
                    try:
                        from api.services.beta_ml import train_model
                        train_result = train_model(db)
                        logger.info("Beta ML training: %s", train_result.get("status", "unknown"))
                    except Exception as e:
                        logger.warning("Beta ML training failed (non-fatal): %s", e)

                    # Step 5c2: Gamma scoring (缠论 buy/sell points)
                    jm.update_progress(job_id, 90, "Gamma评分")
                    try:
                        from api.services.gamma_service import compute_gamma, reset_circuit_breaker
                        from api.models.gamma_factor import GammaSnapshot
                        from api.models.signal import TradingSignal  # Not imported at top level in this file

                        reset_circuit_breaker()
                        buy_signals = (
                            db.query(TradingSignal)
                            .filter(TradingSignal.trade_date == trade_date, TradingSignal.market_regime == "buy")
                            .all()
                        )
                        gamma_count = 0
                        for sig in buy_signals:
                            result = compute_gamma(sig.stock_code, trade_date)
                            if result is None:
                                continue
                            # Update TradingSignal
                            sig.gamma_score = result["gamma_score"]
                            # Upsert GammaSnapshot
                            snap = (
                                db.query(GammaSnapshot)
                                .filter_by(stock_code=sig.stock_code, snapshot_date=trade_date)
                                .first()
                            )
                            if snap:
                                for k, v in result.items():
                                    setattr(snap, k, v)
                            else:
                                db.add(GammaSnapshot(**result))
                            gamma_count += 1
                        db.commit()
                        logger.info("Gamma scorer: %d/%d stocks scored", gamma_count, len(buy_signals))
                    except Exception as e:
                        logger.warning("Gamma scoring failed (non-fatal): %s", e)

                    # Step 5d-pre: Train confidence model from completed trades
                    try:
                        from api.services.confidence_scorer import train_confidence_model
                        cal_result = train_confidence_model(db)
                        logger.info("Confidence model: %s", cal_result.get("status"))
                    except Exception as e:
                        logger.warning("Confidence model training failed (non-fatal): %s", e)

                    # Step 5d: Score signals and create Beta-ranked plans
                    jm.update_progress(job_id, 92, "Beta评分+计划")
                    try:
                        from api.services.beta_scorer import score_and_create_plans
                        from api.services.bot_trading_engine import _get_next_trading_day
                        plan_date = _get_next_trading_day(db, trade_date) or trade_date
                        plans = score_and_create_plans(db, trade_date, plan_date)
                        if plans:
                            logger.info("Beta scorer: %d plans created for %s", len(plans), plan_date)
                    except Exception as e:
                        logger.warning("Beta scoring failed (non-fatal): %s", e)

                    # Step 5e: Create sell plans from sell signals
                    jm.update_progress(job_id, 96, "生成卖出计划")
                    try:
                        from api.routers.signals import _create_sell_plans_from_signals
                        from api.services.bot_trading_engine import _get_next_trading_day
                        plan_date = _get_next_trading_day(db, trade_date) or trade_date
                        sell_count = _create_sell_plans_from_signals(db, trade_date, plan_date)
                        logger.info("Sell plans created for %s: %d", plan_date, sell_count)
                    except Exception as e:
                        logger.warning("Sell plan creation failed (non-fatal): %s", e)

                    logger.info("Daily data sync completed for %s", trade_date)
                    jm.succeed(job_id, f"Sync completed for {trade_date}")
                else:
                    logger.info("Skipped data sync & plans (non-trading day)")
                    jm.succeed(job_id, "Non-trading day, skipped")

                self._last_run_date = trade_date
            finally:
                db.close()
        except Exception as e:
            logger.error("Scheduled data sync failed: %s", e)
            jm.fail(job_id, str(e)[:500])
        finally:
            self._is_refreshing = False
            self._sync_step = ""
            self._sync_total = 0
            self._sync_done = 0

    def _sync_daily_prices(self, db, trade_date: str):
        """Sync daily prices: TDX per-stock (no rate limit) with TuShare batch fallback."""
        from api.services.data_collector import DataCollector
        from api.config import get_settings

        collector = DataCollector(db)
        preferred = get_settings().data_sources.daily_batch

        self._sync_total = 1
        self._sync_done = 0
        logger.info("Syncing daily prices for %s (preferred: %s)...", trade_date, preferred)

        try:
            if preferred == "tdx":
                count = self._sync_daily_via_tdx(collector, trade_date)
                # Fallback to TuShare if TDX got too few records
                if count < 3000:
                    logger.info("TDX got only %d records, trying TuShare batch fallback...", count)
                    count2 = collector._fetch_daily_batch_by_date(trade_date)
                    count = max(count, count2)
            else:
                count = collector._fetch_daily_batch_by_date(trade_date)
            self._sync_done = 1
            logger.info("Daily sync done for %s: %d records", trade_date, count)
        except Exception as e:
            logger.error("Daily sync failed for %s: %s", trade_date, e)
            self._sync_done = 1

    def _sync_daily_via_tdx(self, collector, trade_date: str) -> int:
        """Fetch daily data for all stocks via TDX (per-stock, but no rate limit)."""
        from api.models.stock import Stock, DailyPrice
        from datetime import date

        stocks = collector.db.query(Stock.code).all()
        if not stocks:
            return 0

        trade_d = date.fromisoformat(trade_date)
        # Check which stocks already have data for this date
        existing = set(
            r.stock_code for r in
            collector.db.query(DailyPrice.stock_code)
            .filter(DailyPrice.trade_date == trade_d)
            .all()
        )

        codes = [s.code for s in stocks if s.code not in existing]
        if not codes:
            logger.info("TDX sync: all %d stocks already have data for %s", len(stocks), trade_date)
            return len(existing)

        self._sync_total = len(codes)
        self._sync_done = 0
        logger.info("TDX sync: fetching %d stocks for %s (%d already cached)",
                     len(codes), trade_date, len(existing))

        added = 0
        for i, code in enumerate(codes):
            try:
                df = collector._fetch_daily_tdx(code, trade_date, trade_date)
                if df is not None and not df.empty:
                    collector._cache_daily(code, df)
                    added += 1
            except Exception:
                pass
            self._sync_done = i + 1
            if (i + 1) % 500 == 0:
                collector.db.commit()
                logger.info("TDX sync progress: %d/%d fetched, %d added", i + 1, len(codes), added)

        collector.db.commit()
        return added + len(existing)


# ── Global singleton ──────────────────────────────

_scheduler: Optional[SignalScheduler] = None


def get_signal_scheduler() -> SignalScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        hour, minute = 15, 30
        try:
            from pathlib import Path
            import yaml

            config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                signals_cfg = cfg.get("signals", {})
                hour = signals_cfg.get("auto_refresh_hour", 15)
                minute = signals_cfg.get("auto_refresh_minute", 30)
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
