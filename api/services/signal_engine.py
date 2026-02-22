"""Signal generation service — evaluates strategy buy/sell conditions on stock data."""

import json
import logging
from typing import Optional, Generator

import pandas as pd
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

# Fixed indicator params used for Alpha scoring (never changes per strategy)
_SCORING_CONFIG = IndicatorConfig(
    ma_periods=[20],
    ema_periods=[],
    rsi_periods=[14],
    macd_params_list=[(12, 26, 9)],
    kdj_params_list=[(9, 3, 3)],
    adx_periods=[],
    atr_periods=[],
    calc_obv=False,
)


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
        strategy_ids: Optional[list[int]] = None,
    ) -> list[dict]:
        """Generate signals for given stocks on a given date.

        Args:
            strategy_ids: If provided, only use these strategy IDs.
                          Otherwise, use all enabled strategies.
        """
        if stock_codes is None:
            stock_codes = self.collector.get_sample_stock_codes(20)

        query = self.db.query(Strategy).filter(Strategy.enabled.is_(True))
        if strategy_ids:
            query = query.filter(Strategy.id.in_(strategy_ids))
        strategies = query.all()
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

        Supports both regular strategies (buy_conditions AND mode) and combo
        strategies (portfolio_config.type == "combo" with member voting).
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

        # Pre-load member strategies for combo strategies (cache by strat id)
        combo_members_cache: dict[int, list[Strategy]] = {}

        for strat in strategies:
            pf_config = strat.portfolio_config or {}
            is_combo = pf_config.get("type") == "combo"

            if is_combo:
                # ── Combo strategy: vote across members ──
                member_ids = pf_config.get("member_ids", [])
                if strat.id not in combo_members_cache:
                    combo_members_cache[strat.id] = (
                        self.db.query(Strategy)
                        .filter(Strategy.id.in_(member_ids))
                        .all()
                    )
                members = combo_members_cache[strat.id]
                vote_threshold = pf_config.get("vote_threshold", 2)
                sell_mode = pf_config.get("sell_mode", "any")

                # Collect all member indicators for unified computation
                all_member_conds = []
                for m in members:
                    all_member_conds.extend(m.buy_conditions or [])
                    all_member_conds.extend(m.sell_conditions or [])
                if not all_member_conds:
                    continue

                collected = collect_indicator_params(all_member_conds)
                config = IndicatorConfig.from_collected_params(collected)
                full_df = self.indicator_engine.compute(df, config=config)

                # Count buy votes
                buy_votes = 0
                voting_members: list[str] = []
                for m in members:
                    m_buy = m.buy_conditions or []
                    if m_buy:
                        triggered, _ = evaluate_conditions(m_buy, full_df, mode="AND")
                        if triggered:
                            buy_votes += 1
                            voting_members.append(m.name)

                if buy_votes >= vote_threshold:
                    buy_triggered = True
                    buy_strategies.append(f"{strat.name}({buy_votes}/{len(members)}票)")

                # Count sell votes (only for held stocks)
                if is_held:
                    sell_votes = 0
                    for m in members:
                        m_sell = m.sell_conditions or []
                        if m_sell:
                            triggered, _ = evaluate_conditions(m_sell, full_df, mode="OR")
                            if triggered:
                                sell_votes += 1

                    if sell_mode == "any" and sell_votes > 0:
                        sell_triggered = True
                        sell_strategies.append(strat.name)
                    elif sell_mode == "majority" and sell_votes > len(members) / 2:
                        sell_triggered = True
                        sell_strategies.append(strat.name)
            else:
                # ── Regular strategy ──
                buy_conds = strat.buy_conditions or []
                sell_conds = strat.sell_conditions or []

                all_conds = buy_conds + sell_conds
                if not all_conds:
                    continue

                collected = collect_indicator_params(all_conds)
                config = IndicatorConfig.from_collected_params(collected)
                full_df = self.indicator_engine.compute(df, config=config)

                if buy_conds:
                    triggered, _ = evaluate_conditions(buy_conds, full_df, mode="AND")
                    if triggered:
                        buy_triggered = True
                        buy_strategies.append(strat.name)

                if is_held and sell_conds:
                    triggered, _ = evaluate_conditions(sell_conds, full_df, mode="OR")
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

        # Alpha scoring — only for buy signals
        alpha_score = 0.0
        score_breakdown = {"oversold": 0.0, "consensus": 0.0, "volume_price": 0.0}
        if action == "buy":
            alpha_score, score_breakdown = self._compute_alpha_score(
                df, buy_strategies, len(strategies)
            )

        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "trade_date": trade_date,
            "action": action,
            "reasons": reasons,
            "sentiment_score": sentiment_score,
            "alpha_score": alpha_score,
            "score_breakdown": score_breakdown,
        }

    # ── Alpha scoring ─────────────────────────────────────

    def _compute_alpha_score(
        self,
        df: pd.DataFrame,
        buy_strategies: list[str],
        total_strategies: int,
    ) -> tuple[float, dict]:
        """Compute Alpha score for a stock that triggered buy signals.

        Returns:
            (total_score, {"oversold": x, "consensus": y, "volume_price": z})
        """
        scored_df = self.indicator_engine.compute(df, config=_SCORING_CONFIG)
        if scored_df is None or scored_df.empty or len(scored_df) < 2:
            return 0.0, {"oversold": 0.0, "consensus": 0.0, "volume_price": 0.0}

        latest = scored_df.iloc[-1]
        prev = scored_df.iloc[-2]

        # ── 1. Oversold depth (0-30) ──
        rsi_val = latest.get("RSI_14")
        rsi_score = max(0.0, (30 - (rsi_val or 50)) / 30 * 15) if rsi_val is not None and not pd.isna(rsi_val) else 0.0

        kdj_k = latest.get("KDJ_K_9_3_3")
        kdj_score = max(0.0, (20 - (kdj_k or 50)) / 20 * 10) if kdj_k is not None and not pd.isna(kdj_k) else 0.0

        macd_hist = latest.get("MACD_hist_12_26_9")
        macd_prev = prev.get("MACD_hist_12_26_9")
        macd_turning = 5.0 if (
            macd_hist is not None and macd_prev is not None
            and not pd.isna(macd_hist) and not pd.isna(macd_prev)
            and float(macd_hist) > float(macd_prev)
        ) else 0.0

        oversold = min(30.0, rsi_score + kdj_score + macd_turning)

        # ── 2. Multi-strategy consensus (0-40) ──
        consensus = (len(buy_strategies) / max(total_strategies, 1)) * 40.0

        # ── 3. Volume-price (0-30) ──
        vol = latest.get("volume")
        vol_ma5 = scored_df["volume"].iloc[-5:].mean() if len(scored_df) >= 5 else None
        if vol is not None and vol_ma5 is not None and vol_ma5 > 0 and not pd.isna(vol):
            vol_ratio_score = min(15.0, max(0.0, (float(vol) / float(vol_ma5) - 1) * 10))
        else:
            vol_ratio_score = 0.0

        close = latest.get("close")
        ma20 = latest.get("MA_20")
        if close is not None and ma20 is not None and ma20 > 0 and not pd.isna(close) and not pd.isna(ma20):
            ma_deviation = (float(ma20) - float(close)) / float(ma20) * 100
            ma_score = min(15.0, max(0.0, ma_deviation * 3))
        else:
            ma_score = 0.0

        volume_price = min(30.0, vol_ratio_score + ma_score)

        total = round(oversold + consensus + volume_price, 1)
        breakdown = {
            "oversold": round(oversold, 1),
            "consensus": round(consensus, 1),
            "volume_price": round(volume_price, 1),
        }
        return total, breakdown

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
        action_label = {"buy": "买入", "sell": "卖出"}.get(action, "持有")
        alpha = sig.get("alpha_score", 0.0)
        breakdown = sig.get("score_breakdown") or {}

        if existing:
            existing.final_score = alpha
            existing.swing_score = breakdown.get("oversold", 0.0)
            existing.trend_score = breakdown.get("volume_price", 0.0)
            existing.signal_level = {"buy": 4, "sell": 2}.get(action, 3)
            existing.signal_level_name = action_label
            existing.reasons = reasons_json
            existing.market_regime = action
        else:
            self.db.add(TradingSignal(
                stock_code=sig["stock_code"],
                trade_date=trade_date,
                final_score=alpha,
                swing_score=breakdown.get("oversold", 0.0),
                trend_score=breakdown.get("volume_price", 0.0),
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

        alpha_score = row.final_score or 0.0
        oversold = row.swing_score or 0.0
        volume_price = row.trend_score or 0.0
        consensus = round(max(0.0, alpha_score - oversold - volume_price), 1)

        return {
            "stock_code": row.stock_code,
            "stock_name": stock_name,
            "trade_date": row.trade_date,
            "final_score": alpha_score,
            "alpha_score": alpha_score,
            "oversold_score": oversold,
            "consensus_score": consensus,
            "volume_price_score": volume_price,
            "signal_level": row.signal_level,
            "signal_level_name": row.signal_level_name,
            "action": row.market_regime or "hold",
            "reasons": reasons_list,
        }
