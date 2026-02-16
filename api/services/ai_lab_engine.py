"""AI Lab engine — orchestrates strategy generation, validation, and backtesting.

Execution is decoupled from SSE streaming: experiments run in background threads
and push events to a shared ExperimentProgress buffer. SSE consumers read from
the buffer independently, supporting reconnection.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Generator

from api.models.ai_lab import Experiment, ExperimentStrategy
from api.models.backtest import BacktestRun, BacktestTrade
from api.models.base import SessionLocal
from api.services.data_collector import DataCollector
from api.services.deepseek_client import DeepSeekClient
from api.services.indicator_registry import (
    get_all_fields,
    get_extended_field_group,
    is_extended_indicator,
    EXTENDED_INDICATORS,
)
from src.signals.rule_engine import (
    get_field_group,
    validate_rule,
    collect_indicator_params,
    check_reachability,
    INDICATOR_GROUPS,
)
from src.indicators.indicator_calculator import IndicatorConfig, IndicatorCalculator
from src.backtest.portfolio_engine import PortfolioBacktestEngine, SignalExplosionError, BacktestTimeoutError

logger = logging.getLogger(__name__)

# Limit concurrent backtests to avoid SQLite contention (P14)
_BACKTEST_SEMAPHORE = threading.Semaphore(3)


# ── Progress buffer (thread-safe, multi-consumer) ──────────

class ExperimentProgress:
    """Thread-safe event buffer that supports multiple SSE consumers."""

    def __init__(self):
        self.events: list[str] = []
        self.finished = False
        self._cond = threading.Condition()

    def push(self, data: dict):
        """Push an SSE event (called from background thread)."""
        event = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        with self._cond:
            self.events.append(event)
            self._cond.notify_all()

    def finish(self):
        """Mark the stream as complete (no more events)."""
        with self._cond:
            self.finished = True
            self._cond.notify_all()

    def iter_from(self, start: int = 0) -> Generator[str, None, None]:
        """Yield SSE events starting from index. Blocks for new events."""
        idx = start
        while True:
            # Grab new events under the lock
            with self._cond:
                while idx >= len(self.events) and not self.finished:
                    if not self._cond.wait(timeout=30):
                        break  # timeout → send keepalive

                new_events = self.events[idx:]
                done = self.finished
                idx += len(new_events)

            # Yield outside the lock
            if new_events:
                for ev in new_events:
                    yield ev
            elif not done:
                yield ": keepalive\n\n"

            if done and idx >= len(self.events):
                return


# ── Experiment runner (singleton) ──────────────────────────

class ExperimentRunner:
    """Manages background experiment threads and their progress buffers."""

    # Max time for an entire experiment (all strategies) before watchdog kills it
    MAX_EXPERIMENT_SECONDS = 3600  # 60 minutes

    def __init__(self):
        self._progress: dict[int, ExperimentProgress] = {}
        self._start_times: dict[int, float] = {}
        self._lock = threading.Lock()
        self._watchdog_started = False

    def _ensure_watchdog(self):
        """Start the watchdog thread if not already running."""
        if self._watchdog_started:
            return
        self._watchdog_started = True
        t = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="experiment-watchdog",
        )
        t.start()
        logger.info("Experiment watchdog started (timeout=%ds)", self.MAX_EXPERIMENT_SECONDS)

    def _watchdog_loop(self):
        """Periodically check for experiments that exceeded the time limit."""
        while True:
            time.sleep(60)
            now = time.time()
            expired = []
            with self._lock:
                for eid, start_t in list(self._start_times.items()):
                    p = self._progress.get(eid)
                    if p and not p.finished and (now - start_t) > self.MAX_EXPERIMENT_SECONDS:
                        expired.append(eid)

            for eid in expired:
                elapsed_min = (now - self._start_times.get(eid, now)) / 60
                logger.warning(
                    "Watchdog: experiment %d exceeded %d min (running %.1f min), marking failed",
                    eid, self.MAX_EXPERIMENT_SECONDS // 60, elapsed_min,
                )
                db = SessionLocal()
                try:
                    exp = db.query(Experiment).get(eid)
                    if exp and exp.status not in ("done", "failed"):
                        exp.status = "failed"
                        # Mark remaining pending/backtesting strategies
                        strats = db.query(ExperimentStrategy).filter(
                            ExperimentStrategy.experiment_id == eid,
                            ExperimentStrategy.status.in_(["pending", "backtesting"]),
                        ).all()
                        for s in strats:
                            s.status = "invalid"
                            s.error_message = f"看门狗超时: 实验运行{elapsed_min:.0f}分钟超限"
                            s.score = 0.0
                        db.commit()
                        logger.info("Watchdog: marked %d strategies as invalid for experiment %d", len(strats), eid)
                except Exception as e:
                    logger.error("Watchdog DB update failed for experiment %d: %s", eid, e)
                    db.rollback()
                finally:
                    db.close()

                # Force-finish the progress so SSE clients disconnect
                p = self._progress.get(eid)
                if p and not p.finished:
                    p.push({"type": "error", "message": f"看门狗超时: 实验运行{elapsed_min:.0f}分钟, 强制终止"})
                    p.finish()

    def start(self, experiment_id: int) -> ExperimentProgress:
        """Spawn a background thread for the experiment. Returns its progress buffer."""
        self._ensure_watchdog()
        progress = ExperimentProgress()
        with self._lock:
            self._progress[experiment_id] = progress
            self._start_times[experiment_id] = time.time()

        t = threading.Thread(
            target=self._run_in_thread,
            args=(experiment_id, progress),
            daemon=True,
            name=f"experiment-{experiment_id}",
        )
        t.start()
        return progress

    def get_progress(self, experiment_id: int) -> ExperimentProgress | None:
        """Get the progress buffer for a running experiment."""
        with self._lock:
            return self._progress.get(experiment_id)

    def is_running(self, experiment_id: int) -> bool:
        with self._lock:
            p = self._progress.get(experiment_id)
            return p is not None and not p.finished

    def _run_in_thread(self, experiment_id: int, progress: ExperimentProgress):
        """Run experiment in a background thread with its own DB session."""
        db = SessionLocal()
        try:
            engine = AILabEngine(db)
            engine.run_experiment(experiment_id, progress)
        except Exception as e:
            logger.error("Experiment %d crashed: %s", experiment_id, e, exc_info=True)
            try:
                exp = db.query(Experiment).get(experiment_id)
                if exp and exp.status not in ("done", "failed"):
                    exp.status = "failed"
                    db.commit()
            except Exception:
                pass
            progress.push({"type": "error", "message": f"实验异常: {e}"})
        finally:
            progress.finish()
            db.close()
            # Clean up after a delay so reconnecting clients can still read
            threading.Timer(300, self._cleanup, args=(experiment_id,)).start()

    def resume(self, experiment_id: int) -> ExperimentProgress:
        """Resume backtests for pending strategies in an experiment."""
        if self.is_running(experiment_id):
            return self.get_progress(experiment_id)

        self._ensure_watchdog()
        progress = ExperimentProgress()
        with self._lock:
            self._progress[experiment_id] = progress
            self._start_times[experiment_id] = time.time()

        t = threading.Thread(
            target=self._resume_in_thread,
            args=(experiment_id, progress),
            daemon=True,
            name=f"experiment-resume-{experiment_id}",
        )
        t.start()
        return progress

    def _resume_in_thread(self, experiment_id: int, progress: ExperimentProgress):
        """Resume backtests in a background thread with its own DB session."""
        db = SessionLocal()
        try:
            engine = AILabEngine(db)
            engine.resume_backtests(experiment_id, progress)
        except Exception as e:
            logger.error("Resume experiment %d crashed: %s", experiment_id, e, exc_info=True)
            try:
                exp = db.query(Experiment).get(experiment_id)
                if exp and exp.status not in ("done", "failed"):
                    exp.status = "failed"
                    db.commit()
            except Exception:
                pass
            progress.push({"type": "error", "message": f"恢复回测异常: {e}"})
        finally:
            progress.finish()
            db.close()
            threading.Timer(300, self._cleanup, args=(experiment_id,)).start()

    def _cleanup(self, experiment_id: int):
        with self._lock:
            p = self._progress.get(experiment_id)
            if p and p.finished:
                del self._progress[experiment_id]
            self._start_times.pop(experiment_id, None)


# Module-level singleton
_runner = ExperimentRunner()


def get_runner() -> ExperimentRunner:
    return _runner


# ── Scoring ────────────────────────────────────────────────

def _sigmoid(x: float, center: float = 0, scale: float = 1) -> float:
    """Map x to (0, 1) via sigmoid. center=midpoint, scale=steepness."""
    import math
    z = (x - center) / scale
    return 1 / (1 + math.exp(-z))


def _compute_score(result, weights: dict | None = None) -> float:
    """Composite score with configurable weights.

    Args:
        result: backtest result with total_return_pct, max_drawdown_pct, etc.
        weights: {weight_return, weight_drawdown, weight_sharpe, weight_plr}
                 defaults to 0.30/0.25/0.25/0.20 if not provided.

    Returns a value in [0, 1] with much better discrimination than raw Calmar.
    """
    w = weights or {}
    w_ret = w.get("weight_return", 0.30)
    w_dd = w.get("weight_drawdown", 0.25)
    w_sharpe = w.get("weight_sharpe", 0.25)
    w_plr = w.get("weight_plr", 0.20)

    # Normalize return: 0%→0.5, +50%→0.85, -50%→0.15
    ret_score = _sigmoid(result.total_return_pct, center=0, scale=30)

    # Normalize drawdown: lower is better (0%→1.0, 20%→0.7, 50%→0.3)
    dd = abs(result.max_drawdown_pct) if result.max_drawdown_pct else 0
    dd_score = 1 - _sigmoid(dd, center=30, scale=15)

    # Normalize Sharpe: 0→0.5, 1.0→0.75, 2.0→0.9
    sharpe = result.sharpe_ratio if result.sharpe_ratio else 0
    sharpe_score = _sigmoid(sharpe, center=0, scale=1.5)

    # Normalize profit/loss ratio: 1.0→0.5, 2.0→0.75, 3.0→0.85
    plr = result.profit_loss_ratio if result.profit_loss_ratio else 0
    plr_score = _sigmoid(plr, center=1.0, scale=1.5)

    score = (
        w_ret * ret_score
        + w_dd * dd_score
        + w_sharpe * sharpe_score
        + w_plr * plr_score
    )

    # Severe drawdown penalty: >80% → halve the score
    if dd > 80:
        score *= 0.5

    return score


# ── Engine ─────────────────────────────────────────────────

class AILabEngine:
    """Orchestrate: AI generation → validation → backtest → scoring."""

    def __init__(self, db):
        self.db = db
        self.collector = DataCollector(db)
        self.deepseek = DeepSeekClient()

    def run_experiment(self, experiment_id: int, progress: ExperimentProgress):
        """Run a full experiment, pushing events to the progress buffer."""
        exp = self.db.query(Experiment).get(experiment_id)
        if not exp:
            progress.push({"type": "error", "message": "实验不存在"})
            return

        # ── Phase 1: Generate strategies via AI ──────────────
        exp.status = "generating"
        self.db.commit()

        progress.push({"type": "generating", "message": "正在用 AI 生成策略变体..."})

        try:
            prompt = self._build_prompt(exp)
            raw_strategies = self.deepseek.generate_strategies(prompt)
        except Exception as e:
            logger.error("DeepSeek call failed: %s", e)
            exp.status = "failed"
            self.db.commit()
            progress.push({"type": "error", "message": f"AI 生成失败: {e}"})
            return

        if not raw_strategies:
            exp.status = "failed"
            self.db.commit()
            progress.push({"type": "error", "message": "AI 未返回任何策略"})
            return

        # ── Phase 2: Validate and persist strategies ─────────
        strategies: list[ExperimentStrategy] = []
        for raw in raw_strategies:
            strat = self._validate_and_create(exp.id, raw)
            strategies.append(strat)

        exp.strategy_count = len(strategies)
        self.db.commit()

        progress.push({
            "type": "strategies_ready",
            "count": len(strategies),
            "strategies": [
                {"id": s.id, "name": s.name, "status": s.status}
                for s in strategies
            ],
        })

        # ── Phase 3: Run backtests ───────────────────────────
        exp.status = "backtesting"
        self.db.commit()

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")

        # Data integrity check — repair any gap dates before loading
        progress.push({"type": "data_integrity", "message": "数据完整性检查..."})
        try:
            def _repair_progress(current, total, msg):
                progress.push({
                    "type": "data_integrity",
                    "message": msg,
                    "current": current,
                    "total": total,
                })

            repair_result = self.collector.repair_daily_gaps(
                start_date, end_date, progress_callback=_repair_progress,
            )
            if repair_result["repaired_dates"] > 0:
                logger.info(
                    "AI Lab data repair: %d dates repaired, %d records added",
                    repair_result["repaired_dates"],
                    repair_result["records_added"],
                )
                progress.push({
                    "type": "data_integrity_done",
                    "message": f"修复了 {repair_result['repaired_dates']} 天的数据缺口",
                })
        except Exception as e:
            logger.warning("Data integrity check failed (non-fatal): %s", e)
            progress.push({
                "type": "data_integrity_warning",
                "message": f"数据完整性检查失败(不影响回测): {e}",
            })

        stock_codes = self.collector.get_stocks_with_data(min_rows=60)
        if not stock_codes:
            exp.status = "failed"
            self.db.commit()
            progress.push({"type": "error", "message": "没有可用的股票数据"})
            return

        progress.push({
            "type": "loading_data",
            "message": f"加载 {len(stock_codes)} 只股票数据...",
        })

        stock_data = {}
        for code in stock_codes:
            df = self.collector.get_daily_df(code, start_date, end_date, local_only=True)
            if df is not None and not df.empty and len(df) >= 60:
                stock_data[code] = df

        if not stock_data:
            exp.status = "failed"
            self.db.commit()
            progress.push({"type": "error", "message": "加载数据后无可用股票"})
            return

        progress.push({
            "type": "data_loaded",
            "stock_count": len(stock_data),
            "start_date": start_date,
            "end_date": end_date,
        })

        # ── Compute market regime labels for the backtest period ──
        regime_map = None
        index_return_pct = 0.0
        try:
            from api.services.regime_service import ensure_regimes, get_regime_map, get_regime_summary
            progress.push({"type": "computing_regimes", "message": "计算市场阶段标签..."})
            ensure_regimes(self.db, start_date, end_date)
            regime_map = get_regime_map(self.db, start_date, end_date)
            summary = get_regime_summary(self.db, start_date, end_date)
            index_return_pct = summary.get("total_index_return_pct", 0.0)
            logger.info("Regime map: %d days, index return %.2f%%", len(regime_map), index_return_pct)
        except Exception as e:
            logger.warning("Regime computation failed (non-fatal): %s", e)
            progress.push({"type": "regime_warning", "message": f"市场阶段计算失败(不影响回测): {e}"})

        total = len(strategies)
        for idx, strat in enumerate(strategies, 1):
            if strat.status == "failed":
                progress.push({
                    "type": "backtest_skip",
                    "index": idx, "total": total,
                    "name": strat.name,
                    "reason": strat.error_message,
                })
                continue

            # ── Reachability pre-check ──
            buy_conds = strat.buy_conditions or []
            if buy_conds:
                reachable, reason = check_reachability(buy_conds)
                if not reachable:
                    strat.status = "invalid"
                    strat.error_message = f"条件不可达: {reason}"
                    strat.score = 0.0
                    self.db.commit()
                    progress.push({
                        "type": "backtest_skip",
                        "index": idx, "total": total,
                        "name": strat.name,
                        "reason": strat.error_message,
                    })
                    continue

            progress.push({
                "type": "backtest_start",
                "index": idx, "total": total,
                "name": strat.name,
            })

            try:
                self._run_single_backtest(
                    strat, stock_data, start_date, end_date, exp,
                    regime_map=regime_map,
                    index_return_pct=index_return_pct,
                )
                progress.push({
                    "type": "backtest_done",
                    "index": idx, "total": total,
                    "name": strat.name,
                    "score": round(strat.score, 2),
                    "total_return_pct": round(strat.total_return_pct, 2),
                    "max_drawdown_pct": round(strat.max_drawdown_pct, 2),
                    "win_rate": round(strat.win_rate, 2),
                    "total_trades": strat.total_trades,
                })
            except Exception as e:
                logger.error("Backtest failed for %s: %s", strat.name, e)
                strat.status = "failed"
                strat.error_message = str(e)[:500]
                self.db.commit()
                progress.push({
                    "type": "backtest_error",
                    "index": idx, "total": total,
                    "name": strat.name,
                    "error": str(e)[:200],
                })

        # ── Phase 4: Done ────────────────────────────────────
        exp.status = "done"
        self.db.commit()

        best = (
            self.db.query(ExperimentStrategy)
            .filter(
                ExperimentStrategy.experiment_id == exp.id,
                ExperimentStrategy.status == "done",
            )
            .order_by(ExperimentStrategy.score.desc())
            .first()
        )

        progress.push({
            "type": "experiment_done",
            "best_score": round(best.score, 2) if best else 0,
            "best_name": best.name if best else "",
            "done_count": sum(1 for s in strategies if s.status == "done"),
            "invalid_count": sum(1 for s in strategies if s.status == "invalid"),
            "failed_count": sum(1 for s in strategies if s.status == "failed"),
        })

    # ── Resume backtests for pending strategies ─────────

    def resume_backtests(self, experiment_id: int, progress: ExperimentProgress):
        """Resume backtests for pending/backtesting strategies in an experiment.

        Skips Phase 1 (generation) and Phase 2 (validation) — only runs backtests
        for strategies that are still pending or stuck in backtesting.
        Also retries strategies with status='failed' if they have buy_conditions.
        """
        exp = self.db.query(Experiment).get(experiment_id)
        if not exp:
            progress.push({"type": "error", "message": "实验不存在"})
            return

        strategies = (
            self.db.query(ExperimentStrategy)
            .filter(ExperimentStrategy.experiment_id == exp.id)
            .order_by(ExperimentStrategy.id)
            .all()
        )

        # Find strategies that need (re)backtesting
        pending = [
            s for s in strategies
            if s.status in ("pending", "backtesting")
            or (s.status == "failed" and s.buy_conditions)
        ]

        if not pending:
            progress.push({"type": "info", "message": "没有待回测的策略"})
            exp.status = "done"
            self.db.commit()
            return

        exp.status = "backtesting"
        self.db.commit()

        progress.push({
            "type": "resume_start",
            "experiment_id": exp.id,
            "pending_count": len(pending),
            "total_count": len(strategies),
        })

        # ── Load data (same as run_experiment Phase 3) ──
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")

        progress.push({"type": "data_integrity", "message": "数据完整性检查..."})
        try:
            repair_result = self.collector.repair_daily_gaps(start_date, end_date)
            if repair_result["repaired_dates"] > 0:
                progress.push({
                    "type": "data_integrity_done",
                    "message": f"修复了 {repair_result['repaired_dates']} 天的数据缺口",
                })
        except Exception as e:
            logger.warning("Data integrity check failed (non-fatal): %s", e)

        stock_codes = self.collector.get_stocks_with_data(min_rows=60)
        if not stock_codes:
            exp.status = "failed"
            self.db.commit()
            progress.push({"type": "error", "message": "没有可用的股票数据"})
            return

        progress.push({"type": "loading_data", "message": f"加载 {len(stock_codes)} 只股票数据..."})
        stock_data = {}
        for code in stock_codes:
            df = self.collector.get_daily_df(code, start_date, end_date, local_only=True)
            if df is not None and not df.empty and len(df) >= 60:
                stock_data[code] = df

        if not stock_data:
            exp.status = "failed"
            self.db.commit()
            progress.push({"type": "error", "message": "加载数据后无可用股票"})
            return

        progress.push({"type": "data_loaded", "stock_count": len(stock_data)})

        # ── Compute regime labels ──
        regime_map = None
        index_return_pct = 0.0
        try:
            from api.services.regime_service import ensure_regimes, get_regime_map, get_regime_summary
            ensure_regimes(self.db, start_date, end_date)
            regime_map = get_regime_map(self.db, start_date, end_date)
            summary = get_regime_summary(self.db, start_date, end_date)
            index_return_pct = summary.get("total_index_return_pct", 0.0)
        except Exception as e:
            logger.warning("Regime computation failed (non-fatal): %s", e)

        # ── Run backtests for pending strategies ──
        total = len(pending)
        for idx, strat in enumerate(pending, 1):
            # ── Reachability pre-check ──
            buy_conds = strat.buy_conditions or []
            if buy_conds:
                reachable, reason = check_reachability(buy_conds)
                if not reachable:
                    strat.status = "invalid"
                    strat.error_message = f"条件不可达: {reason}"
                    strat.score = 0.0
                    self.db.commit()
                    progress.push({
                        "type": "backtest_skip",
                        "index": idx, "total": total,
                        "name": strat.name,
                        "reason": strat.error_message,
                    })
                    continue

            progress.push({
                "type": "backtest_start",
                "index": idx, "total": total,
                "name": strat.name,
            })
            try:
                self._run_single_backtest(
                    strat, stock_data, start_date, end_date, exp,
                    regime_map=regime_map,
                    index_return_pct=index_return_pct,
                )
                progress.push({
                    "type": "backtest_done",
                    "index": idx, "total": total,
                    "name": strat.name,
                    "score": round(strat.score or 0, 2),
                    "total_return_pct": round(strat.total_return_pct or 0, 2),
                    "max_drawdown_pct": round(strat.max_drawdown_pct or 0, 2),
                    "total_trades": strat.total_trades or 0,
                })
            except Exception as e:
                logger.error("Resume backtest failed for %s: %s", strat.name, e)
                strat.status = "failed"
                strat.error_message = str(e)[:500]
                self.db.commit()
                progress.push({
                    "type": "backtest_error",
                    "index": idx, "total": total,
                    "name": strat.name,
                    "error": str(e)[:200],
                })

        # ── Phase 4: Done ──
        exp.status = "done"
        self.db.commit()

        best = (
            self.db.query(ExperimentStrategy)
            .filter(
                ExperimentStrategy.experiment_id == exp.id,
                ExperimentStrategy.status == "done",
            )
            .order_by(ExperimentStrategy.score.desc())
            .first()
        )

        progress.push({
            "type": "experiment_done",
            "best_score": round(best.score, 2) if best else 0,
            "best_name": best.name if best else "",
            "done_count": sum(1 for s in strategies if s.status == "done"),
            "invalid_count": sum(1 for s in strategies if s.status == "invalid"),
            "failed_count": sum(1 for s in strategies if s.status == "failed"),
        })

    # ── Prompt building ───────────────────────────────────

    def _build_prompt(self, exp: Experiment) -> str:
        if exp.source_type == "template":
            return f"请围绕以下策略主题生成变体：\n\n主题: {exp.theme}\n\n策略描述: {exp.source_text}"
        else:
            return f"请解析以下策略描述并生成结构化策略变体：\n\n{exp.source_text}"

    # ── Validation ────────────────────────────────────────

    def _validate_and_create(
        self, experiment_id: int, raw: dict,
    ) -> ExperimentStrategy:
        """Validate AI-generated strategy and create ExperimentStrategy record."""
        name = raw.get("name", "未命名策略")
        desc = raw.get("description", "")
        buy_conds = raw.get("buy_conditions", [])
        sell_conds = raw.get("sell_conditions", [])
        exit_config = raw.get("exit_config", {})

        orig_buy = len(buy_conds)
        orig_sell = len(sell_conds)
        errors = []

        # Validate conditions
        buy_conds, buy_errs = self._validate_conditions(buy_conds)
        sell_conds, sell_errs = self._validate_conditions(sell_conds)
        errors.extend(buy_errs)
        errors.extend(sell_errs)

        # Cap buy conditions at 4 to avoid unreachable AND combinations
        if len(buy_conds) > 4:
            errors.append(f"买入条件过多({len(buy_conds)}个)，截断为4个")
            buy_conds = buy_conds[:4]

        # Remove contradictory buy conditions (e.g., RSI>50 AND RSI<30)
        buy_conds, contra_errs = self._remove_contradictions(buy_conds)
        errors.extend(contra_errs)

        # Validate exit_config
        exit_config = self._validate_exit_config(exit_config)

        # Log validation results
        removed_buy = orig_buy - len(buy_conds)
        removed_sell = orig_sell - len(sell_conds)
        if removed_buy > 0 or removed_sell > 0 or errors:
            logger.warning(
                "策略 '%s': 移除%d个买入条件, %d个卖出条件: %s",
                name, removed_buy, removed_sell,
                "; ".join(errors[:5]),
            )

        status = "pending"
        error_msg = ""
        if not buy_conds and not sell_conds:
            status = "failed"
            error_msg = "无有效的买卖条件"
        elif errors:
            error_msg = "; ".join(errors[:3])

        strat = ExperimentStrategy(
            experiment_id=experiment_id,
            name=name,
            description=desc,
            buy_conditions=buy_conds,
            sell_conditions=sell_conds,
            exit_config=exit_config,
            status=status,
            error_message=error_msg,
        )
        self.db.add(strat)
        self.db.flush()
        return strat

    # Threshold ranges for value-comparison sanity checks
    _THRESHOLD_RANGES: dict[str, tuple[float, float] | None] = {
        "RSI": (0, 100),
        "KDJ_K": (0, 100), "KDJ_D": (0, 100), "KDJ_J": (-20, 120),
        "ATR": (0.1, 500),
        "CCI": (-500, 500),
        "WR": (-100, 0),
        "ADX": (0, 100), "ADX_plus_di": (0, 100), "ADX_minus_di": (0, 100),
        "MFI": (0, 100),
        "OBV": None,  # range too large, skip
        "close": (1, 10000), "open": (1, 10000), "high": (1, 10000), "low": (1, 10000),
        # Extended indicators
        "STOCHRSI_K": (0, 100), "STOCHRSI_D": (0, 100),
        "ROC": (-50, 50),
        "CMF": (-1, 1),
        "TRIX": (-1, 1),
        "DPO": (-100, 100),
        # BOLL/VWAP are price-level — should use field comparison, not value
        "BOLL_upper": None, "BOLL_middle": None, "BOLL_lower": None,
        "VWAP": None,
    }

    @staticmethod
    def _params_equal(p1: dict | None, p2: dict | None) -> bool:
        """Check if two param dicts are equivalent (None/{} treated as equal)."""
        a = p1 or {}
        b = p2 or {}
        return a == b

    @staticmethod
    def _remove_contradictions(
        conditions: list[dict],
    ) -> tuple[list[dict], list[str]]:
        """Detect and remove contradictory value conditions on the same field.

        E.g., RSI > 50 AND RSI < 30 can never be true simultaneously.
        Also catches: field > X AND field < Y where X >= Y.
        """
        errors: list[str] = []
        # Build bounds per (field, params_fingerprint)
        bounds: dict[str, dict] = {}  # key → {"gt": max_lower, "lt": min_upper, indices: []}
        for i, cond in enumerate(conditions):
            if cond.get("compare_type", "value") != "value":
                continue
            field = cond.get("field", "")
            params = cond.get("params") or {}
            key = f"{field}|{sorted(params.items())}"
            if key not in bounds:
                bounds[key] = {"gt": None, "lt": None, "indices": []}
            b = bounds[key]
            b["indices"].append(i)
            try:
                val = float(cond.get("compare_value", 0))
            except (ValueError, TypeError):
                continue
            op = cond.get("operator", "")
            if op in (">", ">="):
                if b["gt"] is None or val > b["gt"]:
                    b["gt"] = val
            elif op in ("<", "<="):
                if b["lt"] is None or val < b["lt"]:
                    b["lt"] = val

        # Check for impossible ranges
        remove_indices: set[int] = set()
        for key, b in bounds.items():
            if b["gt"] is not None and b["lt"] is not None and b["gt"] >= b["lt"]:
                field_name = key.split("|")[0]
                errors.append(
                    f"条件矛盾: {field_name} 要求 >{b['gt']} 且 <{b['lt']}，不可能同时满足"
                )
                # Remove all value-conditions for this field to salvage other conditions
                for idx in b["indices"]:
                    remove_indices.add(idx)

        if not remove_indices:
            return conditions, errors
        return [c for i, c in enumerate(conditions) if i not in remove_indices], errors

    def _validate_conditions(
        self, conditions: list[dict],
    ) -> tuple[list[dict], list[str]]:
        """Validate and fix conditions. Returns (fixed_conditions, errors)."""
        valid = []
        errors = []

        for cond in conditions:
            field = cond.get("field", "")
            # Check built-in first, then extended
            group = get_field_group(field)
            if not group and not is_extended_indicator(field):
                errors.append(f"不支持的指标: {field}")
                continue

            # Validate operator
            op = cond.get("operator", "")
            if op not in (">", "<", ">=", "<="):
                errors.append(f"无效运算符: {op}")
                continue

            # Validate compare side
            ctype = cond.get("compare_type", "value")
            if ctype == "value":
                try:
                    val = float(cond.get("compare_value", 0))
                except (ValueError, TypeError):
                    errors.append(f"比较值不是数字: {cond.get('compare_value')}")
                    continue

                # ── Threshold sanity check ──
                rng = self._THRESHOLD_RANGES.get(field)
                if rng is not None:
                    lo, hi = rng
                    if val < lo or val > hi:
                        errors.append(f"阈值超出范围: {field} 比较值 {val} 不在 [{lo}, {hi}]")
                        continue
                # Price fields with value < 2.0 → likely percentage misuse
                if field in ("close", "open", "high", "low") and val < 2.0:
                    errors.append(f"价格阈值异常: {field} 比较值 {val} < 2.0（疑似百分比误用）")
                    continue

            elif ctype == "field":
                cf = cond.get("compare_field", "")
                price_fields = {"close", "open", "high", "low", "volume"}

                # ── P22: Auto-swap reversed field comparisons ──
                if field not in price_fields and cf in price_fields:
                    old_field, old_cf = field, cf
                    cond["field"], cond["compare_field"] = cf, field
                    old_params = cond.get("params")
                    old_cp = cond.get("compare_params")
                    cond["compare_params"] = old_params if old_params else cond.pop("compare_params", None)
                    if old_cp:
                        cond["params"] = old_cp
                    else:
                        cond.pop("params", None)
                    flip = {">": "<", "<": ">", ">=": "<=", "<=": ">="}
                    cond["operator"] = flip.get(cond.get("operator", ">"), ">")
                    errors.append(f"自动修正: {old_field} vs {old_cf} → {cf} vs {field}")
                    field, cf = cf, field

                if not get_field_group(cf) and not is_extended_indicator(cf):
                    errors.append(f"不支持的比较指标: {cf}")
                    continue

                # ── P22: Auto-fill default params for compare_field ──
                if not cond.get("compare_params"):
                    _builtin_defaults = {
                        "MA": {"period": 20}, "EMA": {"period": 20},
                        "PSAR": {"step": 0.02, "max_step": 0.2},
                        "BOLL_upper": {"length": 20, "std": 2.0},
                        "BOLL_middle": {"length": 20, "std": 2.0},
                        "BOLL_lower": {"length": 20, "std": 2.0},
                    }
                    if cf in _builtin_defaults:
                        cond["compare_params"] = _builtin_defaults[cf]
                        errors.append(f"自动填充 {cf} 默认参数: {_builtin_defaults[cf]}")
                    else:
                        ext_group = get_extended_field_group(cf)
                        if ext_group:
                            meta = EXTENDED_INDICATORS[ext_group]
                            if meta["params"]:
                                defaults = {k: v["default"] for k, v in meta["params"].items()}
                                cond["compare_params"] = defaults
                                errors.append(f"自动填充 {cf} 默认参数: {defaults}")

                # ── Same-field comparison detection ──
                cp = cond.get("compare_params") or {}
                p = cond.get("params") or {}
                if cf == field and self._params_equal(p, cp):
                    errors.append(f"移除无效条件: {field} 与自身比较")
                    continue
            else:
                errors.append(f"未知比较类型: {ctype}")
                continue

            valid.append(cond)

        return valid, errors

    def _validate_exit_config(self, config: dict) -> dict:
        """Ensure exit_config has sensible defaults."""
        return {
            "stop_loss_pct": min(float(config.get("stop_loss_pct", -8)), 0),
            "take_profit_pct": max(float(config.get("take_profit_pct", 20)), 0),
            "max_hold_days": max(int(config.get("max_hold_days", 20)), 1),
        }

    # ── Combo config extraction ────────────────────────────

    def _extract_combo_config(self, strat: ExperimentStrategy) -> dict | None:
        """Extract combo config from an ExperimentStrategy.

        Checks three sources in order:
        1. regime_stats with type="combo" (initial run, config not yet consumed)
        2. regime_stats._combo_config (post-successful-run, embedded alongside regime data)
        3. Sibling strategies in same experiment (fallback for retries where regime_stats was cleared)
        """
        import re

        rs = strat.regime_stats
        # Source 1: direct combo config
        if isinstance(rs, dict) and rs.get("type") == "combo":
            return rs
        # Source 2: embedded after successful run
        if isinstance(rs, dict) and isinstance(rs.get("_combo_config"), dict):
            return rs["_combo_config"]
        # Source 3: recover from sibling
        if not (isinstance(strat.description, str) and "个策略同意" in strat.description):
            if not (isinstance(strat.name, str) and strat.name.startswith("投票")):
                return None
        # This looks like a combo strategy — find a sibling with config
        siblings = (
            self.db.query(ExperimentStrategy)
            .filter(
                ExperimentStrategy.experiment_id == strat.experiment_id,
                ExperimentStrategy.id != strat.id,
            )
            .all()
        )
        for s in siblings:
            srs = s.regime_stats
            if not isinstance(srs, dict):
                continue
            if srs.get("type") == "combo":
                base = dict(srs)
            elif isinstance(srs.get("_combo_config"), dict):
                base = dict(srs["_combo_config"])
            else:
                continue
            # Override vote_threshold and sell_mode from this strategy's name
            m = re.match(r"投票(\d+)/(\d+)", strat.name)
            if m:
                base["vote_threshold"] = int(m.group(1))
            if "_多数卖出" in strat.name:
                base["sell_mode"] = "majority"
            logger.info("Recovered combo config for %s from sibling %s", strat.name, s.name)
            return base
        return None

    # ── Quick signal pre-scan (P4) ──────────────────────────
    _PRESCAN_SAMPLE_SIZE = 100
    _PRESCAN_DAYS = 60

    def _quick_signal_check(
        self, strat: ExperimentStrategy, stock_data: dict,
    ) -> bool:
        """Quick pre-scan: sample stocks and check if any buy signal fires.

        Returns True if at least one signal found (strategy is viable).
        Returns False if zero signals across all samples (likely zero-trade).
        """
        import random
        import pandas as pd
        from src.signals.rule_engine import evaluate_conditions

        buy_conditions = strat.buy_conditions or []
        if not buy_conditions:
            return False

        codes = list(stock_data.keys())
        if len(codes) > self._PRESCAN_SAMPLE_SIZE:
            codes = random.sample(codes, self._PRESCAN_SAMPLE_SIZE)

        all_rules = buy_conditions + (strat.sell_conditions or [])
        collected = collect_indicator_params(all_rules)
        config = IndicatorConfig.from_collected_params(collected)
        calculator = IndicatorCalculator(config)

        for code in codes:
            df = stock_data.get(code)
            if df is None or df.empty:
                continue

            df_tail = df.tail(self._PRESCAN_DAYS).copy()
            if len(df_tail) < 10:
                continue

            try:
                indicators = calculator.calculate_all(df_tail)
                df_full = pd.concat(
                    [df_tail.reset_index(drop=True), indicators.reset_index(drop=True)],
                    axis=1,
                )
                for i in range(max(0, len(df_full) - 30), len(df_full)):
                    df_slice = df_full.iloc[: i + 1]
                    triggered, _ = evaluate_conditions(buy_conditions, df_slice, mode="AND")
                    if triggered:
                        return True
            except Exception:
                continue

        return False

    # ── Backtest ──────────────────────────────────────────

    # Per-strategy backtest timeout in seconds (10 minutes, 15 for combo)
    BACKTEST_TIMEOUT_SECONDS = 600
    COMBO_BACKTEST_TIMEOUT_SECONDS = 900

    def _run_single_backtest(
        self,
        strat: ExperimentStrategy,
        stock_data: dict,
        start_date: str,
        end_date: str,
        exp: Experiment = None,
        regime_map: dict | None = None,
        index_return_pct: float = 0.0,
    ):
        """Run portfolio backtest for a single experiment strategy.

        Supports combo strategies: if strat.regime_stats has type="combo",
        loads member strategies and uses voting logic.
        """
        _BACKTEST_SEMAPHORE.acquire()
        try:
            self._run_single_backtest_impl(
                strat, stock_data, start_date, end_date,
                exp, regime_map, index_return_pct,
            )
        finally:
            _BACKTEST_SEMAPHORE.release()

    def _run_single_backtest_impl(
        self,
        strat: ExperimentStrategy,
        stock_data: dict,
        start_date: str,
        end_date: str,
        exp: Experiment = None,
        regime_map: dict | None = None,
        index_return_pct: float = 0.0,
    ):
        """Inner implementation of single backtest (called with semaphore held)."""
        strat.status = "backtesting"
        self.db.commit()

        strategy_dict = {
            "name": strat.name,
            "buy_conditions": strat.buy_conditions or [],
            "sell_conditions": strat.sell_conditions or [],
            "exit_config": strat.exit_config or {},
        }

        # ── Check for combo config ──
        # Combo config may be in regime_stats directly (type=combo), embedded
        # (_combo_config key after a successful run), or recoverable from siblings.
        combo_config = self._extract_combo_config(strat)

        # ── Quick signal pre-scan for non-combo strategies (P4) ──
        if not combo_config and stock_data:
            if not self._quick_signal_check(strat, stock_data):
                strat.status = "invalid"
                strat.error_message = "预扫描: 100只股票×60天无任何买入信号"
                strat.score = 0.0
                self.db.commit()
                logger.info("Pre-scan: zero signals for %s, marking invalid", strat.name)
                return

        if combo_config:
            from api.models.strategy import Strategy as StrategyModel
            member_ids = combo_config.get("member_ids", [])
            members = self.db.query(StrategyModel).filter(StrategyModel.id.in_(member_ids)).all()
            strategy_dict["portfolio_config"] = combo_config
            strategy_dict["member_strategies"] = [
                {
                    "id": m.id,
                    "name": m.name,
                    "buy_conditions": m.buy_conditions or [],
                    "sell_conditions": m.sell_conditions or [],
                    "weight": m.weight,
                }
                for m in members
            ]
            # Don't clear regime_stats here — it will be overwritten after successful backtest

        initial_capital = getattr(exp, "initial_capital", None) or 100000.0
        max_positions = getattr(exp, "max_positions", None) or 10
        max_position_pct = getattr(exp, "max_position_pct", None) or 30.0

        engine = PortfolioBacktestEngine(
            initial_capital=initial_capital,
            max_positions=max_positions,
            max_position_pct=max_position_pct,
        )

        # Set up timeout via cancel_event — combo strategies get longer timeout
        timeout_secs = self.COMBO_BACKTEST_TIMEOUT_SECONDS if combo_config else self.BACKTEST_TIMEOUT_SECONDS
        cancel_event = threading.Event()
        timer = threading.Timer(timeout_secs, cancel_event.set)
        timer.daemon = True
        timer.start()

        try:
            result = engine.run(strategy_dict, stock_data, regime_map=regime_map, cancel_event=cancel_event)
        except SignalExplosionError as e:
            strat.status = "invalid"
            strat.error_message = str(e)
            strat.score = 0.0
            self.db.commit()
            logger.warning("Signal explosion for strategy %s: %s", strat.name, e)
            return
        except BacktestTimeoutError as e:
            strat.status = "invalid"
            strat.error_message = f"回测超时({timeout_secs}秒): {e}"
            strat.score = 0.0
            self.db.commit()
            logger.warning("Backtest timeout for strategy %s: %s", strat.name, e)
            return
        finally:
            timer.cancel()

        # Update strategy record
        strat.total_trades = result.total_trades
        strat.win_rate = result.win_rate
        strat.total_return_pct = result.total_return_pct
        strat.max_drawdown_pct = result.max_drawdown_pct
        strat.avg_hold_days = result.avg_hold_days
        strat.avg_pnl_pct = result.avg_pnl_pct

        # Save regime stats — for combo strategies, embed combo config for retry support
        regime_data = result.regime_stats if result.regime_stats else {}
        if combo_config:
            regime_data["_combo_config"] = combo_config
        strat.regime_stats = regime_data or None

        # Handle zero trades → invalid
        if result.total_trades == 0:
            strat.score = 0.0
            strat.status = "invalid"
            strat.error_message = "零交易: 买入条件在回测期间从未满足"
        else:
            # Load scoring weights from config
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

        # Persist backtest run for detail viewing
        result_dict = {
            "equity_curve": result.equity_curve,
            "sell_reason_stats": result.sell_reason_stats,
        }
        run = BacktestRun(
            strategy_id=None,  # AI lab — no formal strategy
            strategy_name=f"[AI实验] {strat.name}",
            start_date=result.start_date,
            end_date=result.end_date,
            capital_per_trade=result.initial_capital,
            total_trades=result.total_trades,
            win_rate=result.win_rate,
            total_return_pct=result.total_return_pct,
            max_drawdown_pct=result.max_drawdown_pct,
            avg_hold_days=result.avg_hold_days,
            avg_pnl_pct=result.avg_pnl_pct,
            result_json=json.dumps(result_dict, ensure_ascii=False),
            backtest_mode="portfolio",
            initial_capital=result.initial_capital,
            max_positions=result.max_positions,
            cagr_pct=result.cagr_pct,
            sharpe_ratio=result.sharpe_ratio,
            calmar_ratio=result.calmar_ratio,
            profit_loss_ratio=result.profit_loss_ratio,
            regime_stats=result.regime_stats if result.regime_stats else None,
            index_return_pct=index_return_pct,
        )
        self.db.add(run)
        self.db.flush()

        for t in result.trades:
            self.db.add(BacktestTrade(
                run_id=run.id,
                stock_code=t.stock_code,
                strategy_name=t.strategy_name,
                buy_date=t.buy_date,
                buy_price=t.buy_price,
                sell_date=t.sell_date,
                sell_price=t.sell_price,
                sell_reason=t.sell_reason,
                pnl_pct=t.pnl_pct,
                hold_days=t.hold_days,
            ))

        strat.backtest_run_id = run.id
        self.db.commit()

        logger.info(
            "Backtest done for %s: trades=%d win=%.1f%% return=%.1f%% drawdown=%.1f%% "
            "CAGR=%.1f%% sharpe=%.2f score=%.2f",
            strat.name, result.total_trades, result.win_rate,
            result.total_return_pct, result.max_drawdown_pct,
            result.cagr_pct, result.sharpe_ratio, strat.score,
        )
