"""Signal generation service — evaluates strategy buy/sell conditions on stock data."""

import json
import logging
import math
from collections import defaultdict
from typing import Optional, Generator

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models.stock import Stock, Watchlist
from api.models.strategy import Strategy
from api.models.signal import TradingSignal
from api.models.gamma_factor import GammaSnapshot
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

    def _load_portfolio_strategy_map(self) -> dict[str, list[Strategy]]:
        """Load {stock_code: [Strategy]} for all current holdings, including archived strategies.

        This ensures sell conditions from archived strategies are still evaluated
        for positions that were opened under those strategies before rebalancing.
        """
        from api.models.bot_trading import BotPortfolio
        holdings = self.db.query(BotPortfolio).all()

        # Collect unique strategy_ids that have sell conditions
        strat_ids = {h.strategy_id for h in holdings if h.strategy_id}
        strategies_by_id: dict[int, Strategy] = {}
        if strat_ids:
            rows = self.db.query(Strategy).filter(Strategy.id.in_(strat_ids)).all()
            strategies_by_id = {s.id: s for s in rows}

        result: dict[str, list[Strategy]] = {}
        for h in holdings:
            strat = strategies_by_id.get(h.strategy_id) if h.strategy_id else None
            if strat and strat.sell_conditions:
                result.setdefault(h.stock_code, [])
                if strat not in result[h.stock_code]:
                    result[h.stock_code].append(strat)

        return result

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

        query = self.db.query(Strategy).filter(
            Strategy.enabled.is_(True),
            Strategy.archived_at.is_(None),
        )
        if strategy_ids:
            query = query.filter(Strategy.id.in_(strategy_ids))
        strategies = query.all()
        if not strategies:
            return []

        name_map = self._load_name_map()
        held_codes = self._load_watchlist_codes()
        portfolio_strategy_map = self._load_portfolio_strategy_map()
        portfolio_codes = set(portfolio_strategy_map.keys())

        from api.services.news_sentiment_engine import get_sentiment_score_for_signal
        sentiment_score = get_sentiment_score_for_signal(self.db)

        results = []
        for code in stock_codes:
            try:
                signal = self._evaluate_stock(
                    code, trade_date, strategies,
                    stock_name=name_map.get(code, ""),
                    is_held=code in held_codes or code in portfolio_codes,
                    sentiment_score=sentiment_score,
                    portfolio_sell_strategies=portfolio_strategy_map.get(code),
                )
                if signal:
                    results.append(signal)
            except Exception as e:
                logger.warning("Signal gen failed for %s: %s", code, e)
                try:
                    self.db.rollback()
                except Exception:
                    pass

        for sig in results:
            self._save_signal(sig, trade_date)
        self.db.commit()

        # ── Phase 2: Sell scan for ALL portfolio holdings (not just sampled codes) ──
        evaluated_codes = set(stock_codes)
        for code, sell_strats in portfolio_strategy_map.items():
            if code in evaluated_codes:
                continue  # already evaluated above
            try:
                signal = self._evaluate_stock(
                    code, trade_date, [],
                    stock_name=name_map.get(code, ""),
                    is_held=True,
                    sentiment_score=sentiment_score,
                    portfolio_sell_strategies=sell_strats,
                )
                if signal and signal.get("action") == "sell":
                    self._save_signal(signal, trade_date)
                    results.append(signal)
            except Exception as e:
                logger.warning("Portfolio sell scan failed for %s: %s", code, e)
                try:
                    self.db.rollback()
                except Exception:
                    pass
        self.db.commit()

        return results

    # ── SSE streaming generation (all stocks) ─────────────

    def generate_signals_stream(
        self,
        trade_date: str,
        stock_codes: Optional[list[str]] = None,
        strategy_ids: Optional[list[int]] = None,
    ) -> Generator[str, None, None]:
        """Generate signals with SSE progress streaming.

        Yields SSE event strings: data: {json}\\n\\n
        """
        if stock_codes is None:
            stock_codes = self.collector.get_all_stock_codes()

        if not stock_codes:
            yield self._sse_event({"type": "error", "message": "没有可用的股票数据"})
            return

        query = self.db.query(Strategy).filter(
            Strategy.enabled.is_(True),
            Strategy.archived_at.is_(None),
        )
        if strategy_ids:
            query = query.filter(Strategy.id.in_(strategy_ids))
        strategies = query.all()
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

        # ── Phase 1: Buy signal scan across all stocks ────────────────────────
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
                try:
                    self.db.rollback()
                except Exception:
                    pass

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

        # ── Phase 2: Sell signal scan for portfolio holdings only ─────────────
        # Checks sell conditions from each holding's specific strategy (even if archived),
        # covering cases where the strategy was archived after rebalancing.
        portfolio_strategy_map = self._load_portfolio_strategy_map()
        if portfolio_strategy_map:
            logger.info("Phase 2: sell scan for %d portfolio stocks", len(portfolio_strategy_map))
            yield self._sse_event({
                "type": "portfolio_sell_start",
                "total": len(portfolio_strategy_map),
            })
            sell_generated = 0
            for code, sell_strats in portfolio_strategy_map.items():
                stock_name = name_map.get(code, "")
                try:
                    signal = self._evaluate_stock(
                        code, trade_date, [],  # Phase 2: skip buy eval, only sell via portfolio_sell_strategies
                        stock_name=stock_name,
                        is_held=True,
                        sentiment_score=sentiment_score,
                        portfolio_sell_strategies=sell_strats,
                    )
                    if signal and signal.get("action") == "sell":
                        self._save_signal(signal, trade_date)
                        sell_generated += 1
                        yield self._sse_event({"type": "signal", "data": signal})
                except Exception as e:
                    logger.warning("Portfolio sell scan failed for %s: %s", code, e)
                    try:
                        self.db.rollback()
                    except Exception:
                        pass
            self.db.commit()
            generated += sell_generated
            logger.info("Phase 2 done: %d sell signals from portfolio scan", sell_generated)

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
        portfolio_sell_strategies: Optional[list[Strategy]] = None,
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

        # Pre-query per-stock news sentiment (lazy — only computed once per stock)
        _stock_sentiment: dict[str, float | None] = {}

        def _inject_news_sentiment(full_df: pd.DataFrame) -> None:
            """Fill NEWS_SENTIMENT columns with actual DB values if they exist."""
            has_3d = "NEWS_SENTIMENT_3D" in full_df.columns
            has_7d = "NEWS_SENTIMENT_7D" in full_df.columns
            if not has_3d and not has_7d:
                return
            if not _stock_sentiment:
                from api.services.news_stock_matcher import compute_stock_news_sentiment
                _stock_sentiment["3d"] = compute_stock_news_sentiment(self.db, stock_code, window_days=3)
                _stock_sentiment["7d"] = compute_stock_news_sentiment(self.db, stock_code, window_days=7)
            if has_3d and _stock_sentiment["3d"] is not None:
                full_df["NEWS_SENTIMENT_3D"] = _stock_sentiment["3d"]
            if has_7d and _stock_sentiment["7d"] is not None:
                full_df["NEWS_SENTIMENT_7D"] = _stock_sentiment["7d"]

        buy_triggered = False
        buy_strategies: list[str] = []
        buy_strategy_objects: list[Strategy] = []
        sell_triggered = False
        sell_strategies: list[str] = []

        # Pre-load member strategies for combo strategies (cache by strat id)
        combo_members_cache: dict[int, list[Strategy]] = {}

        # Group regular strategies by fingerprint for batch evaluation
        fp_groups: dict[str, list[Strategy]] = defaultdict(list)
        combo_strats: list[Strategy] = []

        for strat in strategies:
            pf_config = strat.portfolio_config or {}
            if pf_config.get("type") == "combo":
                combo_strats.append(strat)
            elif strat.signal_fingerprint:
                fp_groups[strat.signal_fingerprint].append(strat)
            else:
                fp_groups[f"_solo_{strat.id}"].append(strat)

        # ── Group fp_groups by indicator config, compute indicators once per config ──
        # Key: stable string repr of IndicatorConfig → (config, [(fp, group), ...])
        indicator_groups: dict[str, tuple] = {}
        computed_dfs: dict[str, object] = {}  # config_key → computed DataFrame

        for fp, group in fp_groups.items():
            representative = group[0]
            all_conds = (representative.buy_conditions or []) + (representative.sell_conditions or [])
            if not all_conds:
                continue
            collected = collect_indicator_params(all_conds)
            config = IndicatorConfig.from_collected_params(collected)
            config_key = str(sorted(vars(config).items()))
            if config_key not in indicator_groups:
                indicator_groups[config_key] = (config, [])
            indicator_groups[config_key][1].append((fp, group))

        for config_key, (config, fp_group_list) in indicator_groups.items():
            full_df = self.indicator_engine.compute(df, config=config)
            _inject_news_sentiment(full_df)
            computed_dfs[config_key] = full_df  # cache for Phase 2 reuse

            for fp, group in fp_group_list:
                representative = group[0]
                buy_conds = representative.buy_conditions or []
                sell_conds = representative.sell_conditions or []

                if buy_conds:
                    triggered, _ = evaluate_conditions(buy_conds, full_df, mode="AND")
                    if triggered:
                        buy_triggered = True
                        for s in group:
                            buy_strategies.append(s.name)
                            buy_strategy_objects.append(s)
                # Sell conditions are evaluated ONLY via portfolio_sell_strategies (Phase 2),
                # ensuring only the position-owning strategy's exit logic is applied.

        # ── Evaluate combo strategies (unchanged) ──
        for strat in combo_strats:
            pf_config = strat.portfolio_config or {}
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

            all_member_conds = []
            for m in members:
                all_member_conds.extend(m.buy_conditions or [])
                all_member_conds.extend(m.sell_conditions or [])
            if not all_member_conds:
                continue

            collected = collect_indicator_params(all_member_conds)
            config = IndicatorConfig.from_collected_params(collected)
            full_df = self.indicator_engine.compute(df, config=config)
            _inject_news_sentiment(full_df)

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
                buy_strategy_objects.append(strat)
            # Combo sell evaluation handled via portfolio_sell_strategies only.

        # ── Evaluate portfolio-specific sell strategies (the position-owning strategy) ──
        # These are loaded from holdings.strategy_id, covering both active and archived strategies.
        # Group by indicator config and reuse already-computed DataFrames where possible.
        if portfolio_sell_strategies:
            owned_groups: dict[str, tuple] = {}
            for strat in portfolio_sell_strategies:
                sell_conds = strat.sell_conditions or []
                if not sell_conds:
                    continue
                try:
                    collected = collect_indicator_params(sell_conds)
                    config = IndicatorConfig.from_collected_params(collected)
                    config_key = str(sorted(vars(config).items()))
                    if config_key not in owned_groups:
                        owned_groups[config_key] = (config, [])
                    owned_groups[config_key][1].append(strat)
                except Exception as e:
                    logger.warning("Portfolio sell config failed for %s / %s: %s", stock_code, strat.name, e)

            for config_key, (config, strat_list) in owned_groups.items():
                try:
                    # Reuse already-computed df if this indicator config was used in Phase 1
                    full_df = computed_dfs.get(config_key)
                    if full_df is None:
                        full_df = self.indicator_engine.compute(df, config=config)
                        _inject_news_sentiment(full_df)
                    for strat in strat_list:
                        sell_conds = strat.sell_conditions or []
                        triggered, triggered_labels = evaluate_conditions(sell_conds, full_df, mode="OR")
                        if triggered:
                            sell_triggered = True
                            label_str = f"[{', '.join(triggered_labels)}]" if triggered_labels else ""
                            archived_tag = "" if strat.archived_at is None else "(archived)"
                            sell_strategies.append(f"{strat.name}{archived_tag}{label_str}")
                except Exception as e:
                    logger.warning("Portfolio sell eval failed for %s: %s", stock_code, e)

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

        # Build reasons list
        if action == "sell":
            # For sell: extract unique condition labels + count of triggering strategies
            # sell_strategies entries are "StrategyName[label1, label2]" or "StrategyName"
            import re as _re
            seen_labels: set[str] = set()
            label_list: list[str] = []
            for entry in sell_strategies:
                m = _re.search(r'\[([^\]]+)\]$', entry)
                if m:
                    for lbl in m.group(1).split(", "):
                        lbl = lbl.strip()
                        if lbl and lbl not in seen_labels:
                            seen_labels.add(lbl)
                            label_list.append(lbl)
            strat_count = len(set(sell_strategies))
            reasons = label_list if label_list else [f"{strat_count}策略触发"]
            # Prepend strategy count summary
            reasons = [f"{strat_count}策略触发"] + label_list
        else:
            seen: set[str] = set()
            reasons = []
            for name in buy_strategies:
                if name not in seen:
                    seen.add(name)
                    reasons.append(name)

        # Alpha scoring — only for buy signals
        alpha_score = 0.0
        score_breakdown = {"count": 0.0, "quality": 0.0, "diversity": 0.0}
        if action == "buy":
            alpha_score, score_breakdown = self._compute_alpha_score(
                buy_strategy_objects
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
        buy_strategy_objects: list[Strategy],
    ) -> tuple[float, dict]:
        """Compute Alpha score based on strategy activation strength.

        Three dimensions (0-100 total):
        - Count  (0-30): How many strategies triggered buy (log scale)
        - Quality(0-40): Average backtest score of triggering strategies
        - Diversity(0-30): How many unique signal fingerprint families triggered

        Returns:
            (total_score, {"count": x, "quality": y, "diversity": z})
        """
        if not buy_strategy_objects:
            return 0.0, {"count": 0.0, "quality": 0.0, "diversity": 0.0}

        # ── 1. Strategy count (0-30) — log scale ──
        n = len(buy_strategy_objects)
        count_score = min(30.0, 6.0 * math.log2(n + 1))

        # ── 2. Strategy quality (0-40) — average backtest score ──
        scores = []
        for s in buy_strategy_objects:
            bs = s.backtest_summary or {}
            sc = bs.get("score")
            if sc is not None:
                scores.append(float(sc))
        avg_score = sum(scores) / len(scores) if scores else 0.0
        quality_score = avg_score * 40.0

        # ── 3. Skeleton diversity (0-30) — unique fingerprint families ──
        fingerprints = {s.signal_fingerprint for s in buy_strategy_objects if s.signal_fingerprint}
        fp_count = len(fingerprints)
        diversity_score = min(30.0, 10.0 * math.log2(fp_count + 1)) if fp_count > 0 else 0.0

        total = float(round(count_score + quality_score + diversity_score, 1))
        breakdown = {
            "count": float(round(count_score, 1)),
            "quality": float(round(quality_score, 1)),
            "diversity": float(round(diversity_score, 1)),
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
        alpha = float(sig.get("alpha_score", 0.0) or 0.0)
        breakdown = sig.get("score_breakdown") or {}

        if existing:
            existing.final_score = alpha
            existing.swing_score = float(breakdown.get("count", 0.0))
            existing.trend_score = float(breakdown.get("quality", 0.0))
            existing.signal_level = {"buy": 4, "sell": 2}.get(action, 3)
            existing.signal_level_name = action_label
            existing.reasons = reasons_json
            existing.market_regime = action
        else:
            self.db.add(TradingSignal(
                stock_code=sig["stock_code"],
                trade_date=trade_date,
                final_score=alpha,
                swing_score=float(breakdown.get("count", 0.0)),
                trend_score=float(breakdown.get("quality", 0.0)),
                signal_level={"buy": 4, "sell": 2}.get(action, 3),
                signal_level_name=action_label,
                reasons=reasons_json,
                market_regime=action,
            ))

    # ── Queries ───────────────────────────────────────────

    def get_signals_by_date(self, trade_date: str) -> list[dict]:
        """Fetch signals for a given date, with stock names and gamma data."""
        from sqlalchemy import and_
        rows = (
            self.db.query(TradingSignal, Stock.name, GammaSnapshot)
            .outerjoin(Stock, TradingSignal.stock_code == Stock.code)
            .outerjoin(GammaSnapshot, and_(
                GammaSnapshot.stock_code == TradingSignal.stock_code,
                GammaSnapshot.snapshot_date == TradingSignal.trade_date,
            ))
            .filter(TradingSignal.trade_date == trade_date)
            .order_by(TradingSignal.final_score.desc())
            .all()
        )
        return [self._signal_to_dict(sig, name or "", snap) for sig, name, snap in rows]

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
    def _signal_to_dict(row: TradingSignal, stock_name: str = "", snapshot: GammaSnapshot | None = None) -> dict:
        reasons = row.reasons or "[]"
        try:
            reasons_list = json.loads(reasons)
        except (json.JSONDecodeError, TypeError):
            reasons_list = []

        alpha_score = row.final_score or 0.0
        count_score = row.swing_score or 0.0
        quality_score = row.trend_score or 0.0
        diversity_score = round(max(0.0, alpha_score - count_score - quality_score), 1)

        # Gamma fields (default to 0/null when no snapshot)
        gamma_score = row.gamma_score or 0.0

        # Combined score for display purposes.
        # Uses cold-start weights (80/20) as a static approximation.
        # The actual decision-time combined_score lives in BotTradePlan
        # and uses dynamic phase-based weights from _get_gamma_phase().
        if row.gamma_score is not None:
            combined = round((alpha_score / 100.0) * 0.8 + (row.gamma_score / 100.0) * 0.2, 4)
        else:
            combined = round(alpha_score / 100.0, 4)

        return {
            "stock_code": row.stock_code,
            "stock_name": stock_name,
            "trade_date": row.trade_date,
            "final_score": alpha_score,
            "alpha_score": alpha_score,
            "count_score": count_score,
            "quality_score": quality_score,
            "diversity_score": diversity_score,
            "signal_level": row.signal_level,
            "signal_level_name": row.signal_level_name,
            "action": row.market_regime or "hold",
            "reasons": reasons_list,
            # Gamma fields
            "gamma_score": gamma_score,
            "gamma_daily_strength": snapshot.daily_strength if snapshot else 0.0,
            "gamma_weekly_resonance": snapshot.weekly_resonance if snapshot else 0.0,
            "gamma_structure_health": snapshot.structure_health if snapshot else 0.0,
            "gamma_daily_mmd": (
                f"{snapshot.daily_mmd_level}:{snapshot.daily_mmd_type}"
                if snapshot and snapshot.daily_mmd_type else None
            ),
            "gamma_weekly_mmd": (
                f"{snapshot.weekly_mmd_level}:{snapshot.weekly_mmd_type}"
                if snapshot and snapshot.weekly_mmd_type else None
            ),
            "combined_score": combined,
            "beta_score": 0.0,
        }
