"""Signal generation service — evaluates strategy buy/sell conditions on stock data."""

import json
import logging
from typing import Optional, Generator

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models.stock import Stock, Watchlist
from api.models.strategy import Strategy
from api.models.signal import TradingSignal
from api.services.data_collector import DataCollector
from api.services.indicator_engine import IndicatorEngine
from src.signals.rule_engine import (
    evaluate_rules,
    evaluate_conditions,
    collect_indicator_params,
)
from src.indicators.indicator_calculator import IndicatorConfig

logger = logging.getLogger(__name__)


class SignalEngine:
    """Generate trading signals by evaluating strategy buy/sell conditions."""

    def __init__(self, db: Session):
        self.db = db
        self.collector = DataCollector(db)
        self.indicator_engine = IndicatorEngine()

    # ── Helpers ────────────────────────────────────────────

    def _load_name_map(self) -> dict[str, str]:
        """Batch load {code: name} mapping from Stock table."""
        rows = self.db.query(Stock.code, Stock.name).all()
        return {r.code: r.name for r in rows}

    def _load_watchlist_codes(self) -> set[str]:
        """Load stock codes in user's watchlist (held stocks)."""
        rows = self.db.query(Watchlist.stock_code).all()
        return {r.stock_code for r in rows}

    # ── Non-streaming generation (sample stocks) ──────────

    def generate_signals(
        self,
        trade_date: str,
        stock_codes: Optional[list[str]] = None,
    ) -> list[dict]:
        """Generate signals for given stocks on a given date."""
        if stock_codes is None:
            stock_codes = self.collector.get_sample_stock_codes(20)

        strategies = (
            self.db.query(Strategy).filter(Strategy.enabled.is_(True)).all()
        )
        if not strategies:
            return []

        name_map = self._load_name_map()
        held_codes = self._load_watchlist_codes()

        from api.services.news_sentiment_engine import get_sentiment_score_for_signal
        sentiment_score = get_sentiment_score_for_signal(self.db)

        results = []
        for code in stock_codes:
            try:
                signal = self._evaluate_stock(
                    code, trade_date, strategies,
                    stock_name=name_map.get(code, ""),
                    is_held=code in held_codes,
                    sentiment_score=sentiment_score,
                )
                if signal:
                    results.append(signal)
            except Exception as e:
                logger.warning("Signal gen failed for %s: %s", code, e)

        for sig in results:
            self._save_signal(sig, trade_date)
        self.db.commit()

        return results

    # ── SSE streaming generation (all stocks) ─────────────

    def generate_signals_stream(
        self,
        trade_date: str,
        stock_codes: Optional[list[str]] = None,
    ) -> Generator[str, None, None]:
        """Generate signals with SSE progress streaming.

        Yields SSE event strings: data: {json}\\n\\n
        """
        if stock_codes is None:
            stock_codes = self.collector.get_all_stock_codes()

        if not stock_codes:
            yield self._sse_event({"type": "error", "message": "没有可用的股票数据"})
            return

        strategies = (
            self.db.query(Strategy).filter(Strategy.enabled.is_(True)).all()
        )
        if not strategies:
            yield self._sse_event({"type": "error", "message": "没有启用的策略"})
            return

        name_map = self._load_name_map()
        held_codes = self._load_watchlist_codes()

        from api.services.news_sentiment_engine import get_sentiment_score_for_signal
        sentiment_score = get_sentiment_score_for_signal(self.db)

        total = len(stock_codes)
        cached_count = len(self.collector.get_stocks_with_data(min_rows=60))
        generated = 0
        batch_count = 0
        signaled_codes: set[str] = set()  # tracks codes that produced a signal this run

        yield self._sse_event({
            "type": "start",
            "total": total,
            "cached_count": cached_count,
            "trade_date": trade_date,
        })

        for i, code in enumerate(stock_codes, 1):
            stock_name = name_map.get(code, "")
            try:
                signal = self._evaluate_stock(
                    code, trade_date, strategies,
                    stock_name=stock_name,
                    is_held=code in held_codes,
                    sentiment_score=sentiment_score,
                )
                if signal:
                    self._save_signal(signal, trade_date)
                    signaled_codes.add(code)
                    generated += 1
                    batch_count += 1
                    yield self._sse_event({
                        "type": "signal",
                        "data": signal,
                    })
            except Exception as e:
                logger.warning("Signal gen failed for %s: %s", code, e)

            yield self._sse_event({
                "type": "progress",
                "current": i,
                "total": total,
                "pct": round(i / total * 100, 1),
                "stock_code": code,
                "stock_name": stock_name,
            })

            if batch_count >= 50:
                self.db.commit()
                batch_count = 0

        self.db.commit()

        # Full scan completed — remove stale signals for stocks that
        # were scanned but no longer trigger any signal.
        scanned_set = set(stock_codes)
        stale_codes = scanned_set - signaled_codes
        if stale_codes:
            self.db.query(TradingSignal).filter(
                TradingSignal.trade_date == trade_date,
                TradingSignal.stock_code.in_(list(stale_codes)),
            ).delete(synchronize_session="fetch")
            self.db.commit()
            logger.info(
                "Cleaned %d stale signals for date %s",
                len(stale_codes), trade_date,
            )

        yield self._sse_event({
            "type": "done",
            "total_generated": generated,
            "trade_date": trade_date,
        })

    @staticmethod
    def _sse_event(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    # ── Core evaluation ───────────────────────────────────

    def _evaluate_stock(
        self,
        stock_code: str,
        trade_date: str,
        strategies: list[Strategy],
        stock_name: str = "",
        is_held: bool = False,
        sentiment_score: Optional[float] = None,
    ) -> Optional[dict]:
        """Evaluate all enabled strategies on a single stock.

        Uses buy_conditions (AND mode) for buy signals on all stocks,
        sell_conditions (OR mode) for sell signals on watchlist stocks only,
        and rules for overall scoring.
        """
        from datetime import datetime, timedelta
        end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=250)
        start_str = start_dt.strftime("%Y-%m-%d")

        df = self.collector.get_daily_df(stock_code, start_str, trade_date)
        if df is None or df.empty or len(df) < 60:
            return None

        buy_triggered = False
        buy_strategies: list[str] = []
        sell_triggered = False
        sell_strategies: list[str] = []

        for strat in strategies:
            buy_conds = strat.buy_conditions or []
            sell_conds = strat.sell_conditions or []

            all_conds = buy_conds + sell_conds
            if not all_conds:
                continue

            collected = collect_indicator_params(all_conds)
            config = IndicatorConfig.from_collected_params(collected)
            full_df = self.indicator_engine.compute(df, config=config)

            # Buy condition evaluation (AND: all must trigger)
            if buy_conds:
                triggered, _ = evaluate_conditions(
                    buy_conds, full_df, mode="AND",
                )
                if triggered:
                    buy_triggered = True
                    buy_strategies.append(strat.name)

            # Sell condition evaluation — only for held stocks (OR: any triggers)
            if is_held and sell_conds:
                triggered, _ = evaluate_conditions(
                    sell_conds, full_df, mode="OR",
                )
                if triggered:
                    sell_triggered = True
                    sell_strategies.append(strat.name)

        # Determine action — sell takes priority for held stocks
        if sell_triggered:
            action = "sell"
        elif buy_triggered:
            action = "buy"
        else:
            action = "hold"

        # Only emit signal if a strategy actually triggered
        if action == "hold":
            return None

        # Sentiment influence: suppress weak buy signals during strong bearish sentiment
        if sentiment_score is not None and action == "buy" and sentiment_score < 30:
            if len(buy_strategies) < 2:
                return None

        # Matched strategy names (deduplicated, preserving order)
        matched = sell_strategies if action == "sell" else buy_strategies
        seen: set[str] = set()
        reasons = []
        for name in matched:
            if name not in seen:
                seen.add(name)
                reasons.append(name)

        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "trade_date": trade_date,
            "action": action,
            "reasons": reasons,
            "sentiment_score": sentiment_score,
        }

    # ── Persistence ───────────────────────────────────────

    def _save_signal(self, sig: dict, trade_date: str):
        """Upsert signal to DB."""
        existing = (
            self.db.query(TradingSignal)
            .filter(
                TradingSignal.stock_code == sig["stock_code"],
                TradingSignal.trade_date == trade_date,
            )
            .first()
        )
        reasons_json = json.dumps(sig.get("reasons", []), ensure_ascii=False)
        action = sig.get("action", "hold")
        # Map action to a display name for the signal_level_name column
        action_label = {"buy": "买入", "sell": "卖出"}.get(action, "持有")

        if existing:
            existing.final_score = 0.0
            existing.signal_level = {"buy": 4, "sell": 2}.get(action, 3)
            existing.signal_level_name = action_label
            existing.reasons = reasons_json
            existing.market_regime = action
        else:
            self.db.add(TradingSignal(
                stock_code=sig["stock_code"],
                trade_date=trade_date,
                final_score=0.0,
                signal_level={"buy": 4, "sell": 2}.get(action, 3),
                signal_level_name=action_label,
                reasons=reasons_json,
                market_regime=action,
            ))

    # ── Queries ───────────────────────────────────────────

    def get_signals_by_date(self, trade_date: str) -> list[dict]:
        """Fetch signals for a given date, with stock names."""
        rows = (
            self.db.query(TradingSignal, Stock.name)
            .outerjoin(Stock, TradingSignal.stock_code == Stock.code)
            .filter(TradingSignal.trade_date == trade_date)
            .order_by(TradingSignal.final_score.desc())
            .all()
        )
        return [self._signal_to_dict(sig, name or "") for sig, name in rows]

    def get_signal_history(
        self,
        page: int = 1,
        size: int = 50,
        action: Optional[str] = None,
        trade_date: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        """Fetch paginated signal history, with stock names and optional filters."""
        q = (
            self.db.query(TradingSignal, Stock.name)
            .outerjoin(Stock, TradingSignal.stock_code == Stock.code)
        )
        count_q = self.db.query(TradingSignal)

        if action:
            q = q.filter(TradingSignal.market_regime == action)
            count_q = count_q.filter(TradingSignal.market_regime == action)
        if trade_date:
            q = q.filter(TradingSignal.trade_date == trade_date)
            count_q = count_q.filter(TradingSignal.trade_date == trade_date)
        if strategy:
            q = q.filter(TradingSignal.reasons.contains(strategy))
            count_q = count_q.filter(TradingSignal.reasons.contains(strategy))

        q = q.order_by(
            TradingSignal.trade_date.desc(),
            TradingSignal.final_score.desc(),
        )
        total = count_q.count()
        rows = q.offset((page - 1) * size).limit(size).all()
        return [self._signal_to_dict(sig, name or "") for sig, name in rows], total

    def get_signal_meta(self) -> dict:
        """Return metadata about the latest signal generation."""
        last_row = (
            self.db.query(
                TradingSignal.trade_date,
                TradingSignal.created_at,
            )
            .order_by(TradingSignal.created_at.desc())
            .first()
        )
        if not last_row:
            return {
                "last_generated_at": None,
                "last_trade_date": None,
                "signal_count": 0,
            }

        last_trade_date = last_row.trade_date
        signal_count = (
            self.db.query(func.count(TradingSignal.id))
            .filter(TradingSignal.trade_date == last_trade_date)
            .scalar()
        )
        return {
            "last_generated_at": (
                last_row.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if last_row.created_at else None
            ),
            "last_trade_date": last_trade_date,
            "signal_count": signal_count or 0,
        }

    @staticmethod
    def _signal_to_dict(row: TradingSignal, stock_name: str = "") -> dict:
        reasons = row.reasons or "[]"
        try:
            reasons_list = json.loads(reasons)
        except (json.JSONDecodeError, TypeError):
            reasons_list = []

        return {
            "stock_code": row.stock_code,
            "stock_name": stock_name,
            "trade_date": row.trade_date,
            "final_score": row.final_score,
            "signal_level": row.signal_level,
            "signal_level_name": row.signal_level_name,
            "action": row.market_regime or "hold",
            "reasons": reasons_list,
        }
