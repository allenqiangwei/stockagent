"""Backtest engine service — wraps src/backtest/engine.py with DB persistence."""

import json
import logging
from typing import Optional, Generator

from sqlalchemy.orm import Session

from api.models.strategy import Strategy
from api.models.backtest import BacktestRun, BacktestTrade
from api.services.data_collector import DataCollector
from src.backtest.engine import BacktestEngine, BacktestResult, Trade
from src.backtest.portfolio_engine import PortfolioBacktestEngine, PortfolioBacktestResult, SignalExplosionError, BacktestTimeoutError

logger = logging.getLogger(__name__)


class BacktestService:
    """Run backtests and persist results to DB."""

    def __init__(self, db: Session):
        self.db = db
        self.collector = DataCollector(db)

    def run_backtest(
        self,
        strategy_id: int,
        start_date: str,
        end_date: str,
        capital_per_trade: float = 10000.0,
        stock_codes: Optional[list[str]] = None,
    ) -> Generator[str, None, None]:
        """Run backtest with SSE progress. Yields event strings.

        Args:
            strategy_id: Strategy ID
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            capital_per_trade: Capital per trade
            stock_codes: Stock codes to backtest

        Yields:
            SSE event strings: data: {json}\n\n
        """
        strategy = self.db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if not strategy:
            yield self._sse_event({"type": "error", "message": "策略不存在"})
            return

        # Convert ORM to dict format expected by BacktestEngine
        strategy_dict = {
            "id": strategy.id,
            "name": strategy.name,
            "description": strategy.description,

            "buy_conditions": strategy.buy_conditions or [],
            "sell_conditions": strategy.sell_conditions or [],
            "exit_config": strategy.exit_config or {},
            "weight": strategy.weight,
        }

        if not stock_codes:
            stock_codes = self.collector.get_stocks_with_data(min_rows=60)

        # Phase 0: Data integrity check
        yield self._sse_event({
            "type": "progress", "phase": "integrity",
            "pct": 1, "message": "数据完整性检查...",
        })
        try:
            self.collector.repair_daily_gaps(start_date, end_date)
        except Exception as e:
            logger.warning("Data integrity check failed (non-fatal): %s", e)

        # Phase 1: Load data
        stock_data = {}
        total = len(stock_codes)
        for i, code in enumerate(stock_codes, 1):
            yield self._sse_event({
                "type": "progress",
                "phase": "data",
                "current": i,
                "total": total,
                "message": f"加载数据: {code} ({i}/{total})",
                "pct": round(i / total * 50),
            })

            df = self.collector.get_daily_df(code, start_date, end_date, local_only=True)
            if df is not None and not df.empty and len(df) >= 60:
                stock_data[code] = df

        if not stock_data:
            yield self._sse_event({
                "type": "error",
                "message": "没有可用的股票数据",
            })
            return

        # Phase 2: Run backtest
        engine = BacktestEngine(capital_per_trade=capital_per_trade)

        def on_progress(current, total_count, code):
            pass  # We'll track via the result instead

        yield self._sse_event({
            "type": "progress",
            "phase": "backtest",
            "current": 0,
            "total": len(stock_data),
            "message": f"回测中: {len(stock_data)} 只股票...",
            "pct": 50,
        })

        result = engine.run_batch(strategy_dict, stock_data)

        yield self._sse_event({
            "type": "progress",
            "phase": "saving",
            "pct": 90,
            "message": "保存结果...",
        })

        # Phase 3: Persist to DB
        run_id = self._save_result(strategy.id, result)

        # Phase 4: Send final result
        yield self._sse_event({
            "type": "done",
            "pct": 100,
            "run_id": run_id,
            "result": self._result_to_dict(result, run_id),
        })

    def run_backtest_sync(
        self,
        strategy_id: int,
        start_date: str,
        end_date: str,
        capital_per_trade: float = 10000.0,
        stock_codes: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """Run backtest synchronously (non-SSE). Returns result dict."""
        strategy = self.db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if not strategy:
            return None

        strategy_dict = {
            "id": strategy.id,
            "name": strategy.name,

            "buy_conditions": strategy.buy_conditions or [],
            "sell_conditions": strategy.sell_conditions or [],
            "exit_config": strategy.exit_config or {},
        }

        if not stock_codes:
            stock_codes = self.collector.get_stocks_with_data(min_rows=60)

        # Data integrity check
        try:
            self.collector.repair_daily_gaps(start_date, end_date)
        except Exception as e:
            logger.warning("Data integrity check failed (non-fatal): %s", e)

        stock_data = {}
        for code in stock_codes:
            df = self.collector.get_daily_df(code, start_date, end_date, local_only=True)
            if df is not None and not df.empty and len(df) >= 60:
                stock_data[code] = df

        if not stock_data:
            return None

        engine = BacktestEngine(capital_per_trade=capital_per_trade)
        result = engine.run_batch(strategy_dict, stock_data)
        run_id = self._save_result(strategy.id, result)

        return self._result_to_dict(result, run_id)

    # ── Portfolio backtest ─────────────────────────────────

    def run_portfolio_backtest(
        self,
        strategy_id: int,
        start_date: str,
        end_date: str,
        stock_codes: Optional[list[str]] = None,
    ) -> Generator[str, None, None]:
        """Run portfolio backtest with SSE progress. Yields event strings."""
        strategy = self.db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if not strategy:
            yield self._sse_event({"type": "error", "message": "策略不存在"})
            return

        strategy_dict = self._strategy_to_dict(strategy)
        portfolio_config = strategy.portfolio_config or {}
        rank_config = strategy.rank_config

        if not stock_codes:
            stock_codes = self.collector.get_stocks_with_data(min_rows=60)

        # Phase 0: Data integrity check
        yield self._sse_event({
            "type": "progress", "phase": "integrity",
            "pct": 1, "message": "数据完整性检查...",
        })
        try:
            self.collector.repair_daily_gaps(start_date, end_date)
        except Exception as e:
            logger.warning("Data integrity check failed (non-fatal): %s", e)

        # Phase 1: Load data
        stock_data = {}
        total = len(stock_codes)
        for i, code in enumerate(stock_codes, 1):
            yield self._sse_event({
                "type": "progress", "phase": "data",
                "current": i, "total": total,
                "message": f"加载数据: {code} ({i}/{total})",
                "pct": round(i / total * 30),
            })
            df = self.collector.get_daily_df(code, start_date, end_date, local_only=True)
            if df is not None and not df.empty and len(df) >= 60:
                stock_data[code] = df

        if not stock_data:
            yield self._sse_event({"type": "error", "message": "没有可用的股票数据"})
            return

        # Phase 2: Load daily basic data if rank_config has "basic" factors
        daily_basic_data = None
        if rank_config and any(
            f.get("type") == "basic" for f in rank_config.get("factors", [])
        ):
            yield self._sse_event({
                "type": "progress", "phase": "basic_data",
                "pct": 35, "message": "加载基本面数据...",
            })
            # Collect all dates from stock data
            all_dates = set()
            for df in stock_data.values():
                if "date" in df.columns:
                    all_dates.update(df["date"].tolist())
            daily_basic_data = self.collector.prefetch_daily_basic(sorted(all_dates))

        # Phase 3: Run portfolio backtest
        yield self._sse_event({
            "type": "progress", "phase": "backtest",
            "pct": 40, "message": f"组合回测: {len(stock_data)} 只股票...",
        })

        engine = PortfolioBacktestEngine(
            initial_capital=portfolio_config.get("initial_capital", 100000),
            max_positions=portfolio_config.get("max_positions", 10),
            position_sizing=portfolio_config.get("position_sizing", "equal_weight"),
        )

        result = engine.run(
            strategy_dict, stock_data, daily_basic_data, rank_config,
        )

        yield self._sse_event({
            "type": "progress", "phase": "saving", "pct": 90,
            "message": "保存结果...",
        })

        run_id = self._save_portfolio_result(strategy.id, result)

        yield self._sse_event({
            "type": "done", "pct": 100, "run_id": run_id,
            "result": self._portfolio_result_to_dict(result, run_id),
        })

    def run_portfolio_backtest_sync(
        self,
        strategy_id: int,
        start_date: str,
        end_date: str,
        stock_codes: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """Run portfolio backtest synchronously. Returns result dict."""
        strategy = self.db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if not strategy:
            return None

        strategy_dict = self._strategy_to_dict(strategy)
        portfolio_config = strategy.portfolio_config or {}
        rank_config = strategy.rank_config

        if not stock_codes:
            stock_codes = self.collector.get_stocks_with_data(min_rows=60)

        # Data integrity check
        try:
            self.collector.repair_daily_gaps(start_date, end_date)
        except Exception as e:
            logger.warning("Data integrity check failed (non-fatal): %s", e)

        stock_data = {}
        for code in stock_codes:
            df = self.collector.get_daily_df(code, start_date, end_date, local_only=True)
            if df is not None and not df.empty and len(df) >= 60:
                stock_data[code] = df

        if not stock_data:
            return None

        # Load daily basic data if needed
        daily_basic_data = None
        if rank_config and any(
            f.get("type") == "basic" for f in rank_config.get("factors", [])
        ):
            all_dates = set()
            for df in stock_data.values():
                if "date" in df.columns:
                    all_dates.update(df["date"].tolist())
            daily_basic_data = self.collector.prefetch_daily_basic(sorted(all_dates))

        engine = PortfolioBacktestEngine(
            initial_capital=portfolio_config.get("initial_capital", 100000),
            max_positions=portfolio_config.get("max_positions", 10),
            position_sizing=portfolio_config.get("position_sizing", "equal_weight"),
        )

        result = engine.run(
            strategy_dict, stock_data, daily_basic_data, rank_config,
        )
        run_id = self._save_portfolio_result(strategy.id, result)
        return self._portfolio_result_to_dict(result, run_id)

    def _strategy_to_dict(self, strategy: Strategy) -> dict:
        """Convert Strategy ORM to dict format expected by engines.

        For combo strategies (portfolio_config.type == "combo"), loads member
        strategies' buy/sell conditions and attaches them as member_strategies.
        """
        d = {
            "id": strategy.id,
            "name": strategy.name,
            "description": strategy.description,
            "buy_conditions": strategy.buy_conditions or [],
            "sell_conditions": strategy.sell_conditions or [],
            "exit_config": strategy.exit_config or {},
            "weight": strategy.weight,
        }

        pf_config = strategy.portfolio_config or {}
        if pf_config.get("type") == "combo":
            d["portfolio_config"] = pf_config
            member_ids = pf_config.get("member_ids", [])
            if member_ids:
                members = (
                    self.db.query(Strategy)
                    .filter(Strategy.id.in_(member_ids))
                    .all()
                )
                d["member_strategies"] = [
                    {
                        "id": m.id,
                        "name": m.name,
                        "buy_conditions": m.buy_conditions or [],
                        "sell_conditions": m.sell_conditions or [],
                        "weight": m.weight,
                        "score": (m.backtest_summary or {}).get("score", 1.0),
                    }
                    for m in members
                ]

        return d

    def _save_portfolio_result(
        self, strategy_id: int, result: PortfolioBacktestResult
    ) -> int:
        """Persist portfolio backtest result to DB."""
        result_dict = {
            "equity_curve": result.equity_curve,
            "sell_reason_stats": result.sell_reason_stats,
        }

        run = BacktestRun(
            strategy_id=strategy_id,
            strategy_name=result.strategy_name,
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
            # Portfolio-specific columns
            backtest_mode=result.backtest_mode,
            initial_capital=result.initial_capital,
            max_positions=result.max_positions,
            cagr_pct=result.cagr_pct,
            sharpe_ratio=result.sharpe_ratio,
            calmar_ratio=result.calmar_ratio,
            profit_loss_ratio=result.profit_loss_ratio,
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

        self.db.commit()
        return run.id

    @staticmethod
    def _portfolio_result_to_dict(
        result: PortfolioBacktestResult, run_id: int
    ) -> dict:
        return {
            "id": run_id,
            "strategy_name": result.strategy_name,
            "start_date": result.start_date,
            "end_date": result.end_date,
            "capital_per_trade": result.initial_capital,
            "total_trades": result.total_trades,
            "win_trades": result.win_trades,
            "lose_trades": result.lose_trades,
            "win_rate": result.win_rate,
            "total_return_pct": result.total_return_pct,
            "max_drawdown_pct": result.max_drawdown_pct,
            "avg_hold_days": result.avg_hold_days,
            "avg_pnl_pct": result.avg_pnl_pct,
            "equity_curve": result.equity_curve,
            "sell_reason_stats": result.sell_reason_stats,
            "trades": [
                {
                    "stock_code": t.stock_code,
                    "buy_date": t.buy_date,
                    "buy_price": t.buy_price,
                    "sell_date": t.sell_date,
                    "sell_price": t.sell_price,
                    "sell_reason": t.sell_reason,
                    "pnl_pct": t.pnl_pct,
                    "hold_days": t.hold_days,
                }
                for t in result.trades
            ],
            # Portfolio-specific metrics
            "backtest_mode": result.backtest_mode,
            "initial_capital": result.initial_capital,
            "max_positions": result.max_positions,
            "cagr_pct": result.cagr_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "calmar_ratio": result.calmar_ratio,
            "profit_loss_ratio": result.profit_loss_ratio,
        }

    def get_runs(
        self, strategy_id: Optional[int] = None, limit: int = 50
    ) -> list[dict]:
        """Get backtest run history."""
        q = self.db.query(BacktestRun)
        if strategy_id is not None:
            q = q.filter(BacktestRun.strategy_id == strategy_id)
        runs = q.order_by(BacktestRun.created_at.desc()).limit(limit).all()

        return [{
            "id": r.id,
            "strategy_name": r.strategy_name,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "total_trades": r.total_trades,
            "win_rate": r.win_rate,
            "total_return_pct": r.total_return_pct,
            "max_drawdown_pct": r.max_drawdown_pct,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "backtest_mode": r.backtest_mode,
            "cagr_pct": r.cagr_pct,
            "sharpe_ratio": r.sharpe_ratio,
        } for r in runs]

    def get_run_detail(self, run_id: int) -> Optional[dict]:
        """Get full backtest run with trades."""
        run = self.db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
        if not run:
            return None

        trades = (
            self.db.query(BacktestTrade)
            .filter(BacktestTrade.run_id == run_id)
            .order_by(BacktestTrade.buy_date)
            .all()
        )

        # Try to load equity curve from result_json
        equity_curve = []
        sell_reason_stats = {}
        if run.result_json:
            try:
                data = json.loads(run.result_json)
                equity_curve = data.get("equity_curve", [])
                sell_reason_stats = data.get("sell_reason_stats", {})
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "id": run.id,
            "strategy_name": run.strategy_name,
            "start_date": run.start_date,
            "end_date": run.end_date,
            "capital_per_trade": run.capital_per_trade,
            "total_trades": run.total_trades,
            "win_trades": sum(1 for t in trades if t.pnl_pct and t.pnl_pct > 0),
            "lose_trades": sum(1 for t in trades if not t.pnl_pct or t.pnl_pct <= 0),
            "win_rate": run.win_rate,
            "total_return_pct": run.total_return_pct,
            "max_drawdown_pct": run.max_drawdown_pct,
            "avg_hold_days": run.avg_hold_days,
            "avg_pnl_pct": run.avg_pnl_pct,
            "equity_curve": equity_curve,
            "sell_reason_stats": sell_reason_stats,
            "trades": [{
                "stock_code": t.stock_code,
                "strategy_name": t.strategy_name,
                "buy_date": t.buy_date,
                "buy_price": t.buy_price,
                "sell_date": t.sell_date,
                "sell_price": t.sell_price,
                "sell_reason": t.sell_reason,
                "pnl_pct": t.pnl_pct,
                "hold_days": t.hold_days,
            } for t in trades],
            # Portfolio mode fields
            "backtest_mode": run.backtest_mode,
            "initial_capital": run.initial_capital,
            "max_positions": run.max_positions,
            "cagr_pct": run.cagr_pct,
            "sharpe_ratio": run.sharpe_ratio,
            "calmar_ratio": run.calmar_ratio,
            "profit_loss_ratio": run.profit_loss_ratio,
        }

    def _save_result(self, strategy_id: int, result: BacktestResult) -> int:
        """Persist backtest result to DB."""
        result_dict = {
            "equity_curve": result.equity_curve,
            "sell_reason_stats": result.sell_reason_stats,
        }

        run = BacktestRun(
            strategy_id=strategy_id,
            strategy_name=result.strategy_name,
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
        )
        self.db.add(run)
        self.db.flush()  # get run.id

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

        self.db.commit()
        return run.id

    @staticmethod
    def _result_to_dict(result: BacktestResult, run_id: int) -> dict:
        return {
            "id": run_id,
            "strategy_name": result.strategy_name,
            "start_date": result.start_date,
            "end_date": result.end_date,
            "capital_per_trade": result.initial_capital,
            "total_trades": result.total_trades,
            "win_trades": result.win_trades,
            "lose_trades": result.lose_trades,
            "win_rate": result.win_rate,
            "total_return_pct": result.total_return_pct,
            "max_drawdown_pct": result.max_drawdown_pct,
            "avg_hold_days": result.avg_hold_days,
            "avg_pnl_pct": result.avg_pnl_pct,
            "equity_curve": [
                {"date": p["date"], "equity": p["equity"]}
                for p in result.equity_curve
            ],
            "sell_reason_stats": result.sell_reason_stats,
            "trades": [
                {
                    "stock_code": t.stock_code,
                    "buy_date": t.buy_date,
                    "buy_price": t.buy_price,
                    "sell_date": t.sell_date,
                    "sell_price": t.sell_price,
                    "sell_reason": t.sell_reason,
                    "pnl_pct": t.pnl_pct,
                    "hold_days": t.hold_days,
                }
                for t in result.trades
            ],
        }

    @staticmethod
    def _sse_event(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
