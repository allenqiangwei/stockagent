"""Beta factor engine — capture, review, aggregate, and scorecard.

Captures non-technical factors (sentiment, sector heat, valuation, news events)
at AI decision time, evaluates their predictive accuracy after trades complete,
and aggregates knowledge for future AI-assisted stock selection.
"""

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from api.models.beta_factor import BetaSnapshot, BetaReview, BetaInsight

logger = logging.getLogger(__name__)


# ── Stage 1: Capture ─────────────────────────────────────

def capture_beta_snapshots(
    db: Session,
    report_id: int,
    report_date: str,
    recommendations: list[dict],
) -> list[int]:
    """Capture beta factor snapshots for all stocks in an AI report.

    Called after save_report() in ai_analyst.py. Queries existing tables
    for non-technical context — no new data collection needed.

    Returns list of created snapshot IDs.
    """
    if not recommendations:
        return []

    # Shared context (one query each)
    regime = _get_current_regime(db, report_date)
    market_sent = _get_latest_market_sentiment(db)

    snapshot_ids = []
    for rec in recommendations:
        code = rec.get("stock_code", "")
        if not code:
            continue

        try:
            stock = _get_stock(db, code)
            concepts = _get_stock_concepts(db, code)
            sector_heat = _get_sector_heat(db, stock.industry if stock else "", concepts)
            valuation = _get_latest_valuation(db, code, report_date)
            stock_sent = _get_stock_sentiment(db, code)
            events = _get_active_events(db, code, stock.industry if stock else "", report_date)

            # Compute ML feature columns
            ml_features = _compute_ml_features(db, code, report_date, valuation)

            snap = BetaSnapshot(
                stock_code=code,
                stock_name=rec.get("stock_name", stock.name if stock else ""),
                snapshot_date=report_date,
                report_id=report_id,
                market_regime=regime.regime if regime else None,
                market_regime_confidence=regime.confidence if regime else None,
                market_sentiment=market_sent.market_sentiment if market_sent else None,
                sentiment_confidence=market_sent.confidence if market_sent else None,
                industry=stock.industry if stock else None,
                concepts=concepts,
                stock_sentiment=stock_sent.sentiment if stock_sent else None,
                sector_heat_score=sector_heat.heat_score if sector_heat else None,
                sector_trend=sector_heat.trend if sector_heat else None,
                pe=valuation.pe if valuation else None,
                pb=valuation.pb if valuation else None,
                market_cap=valuation.total_mv if valuation else None,
                turnover_rate=valuation.turnover_rate if valuation else None,
                active_events=events,
                action=rec.get("action", ""),
                alpha_score=rec.get("alpha_score"),
                ai_reasoning=rec.get("reason", "")[:500],
                # ML feature columns
                strategy_family=rec.get("strategy_family"),
                final_score=rec.get("alpha_score"),
                entry_price=ml_features.get("entry_price"),
                day_of_week=ml_features.get("day_of_week"),
                stock_return_5d=ml_features.get("stock_return_5d"),
                stock_volatility_20d=ml_features.get("stock_volatility_20d"),
                volume_ratio_5d=ml_features.get("volume_ratio_5d"),
                index_return_5d=ml_features.get("index_return_5d"),
                index_return_20d=ml_features.get("index_return_20d"),
            )
            db.add(snap)
            db.flush()
            snapshot_ids.append(snap.id)
        except Exception as e:
            logger.warning("Beta snapshot failed for %s: %s", code, e)

    if snapshot_ids:
        db.commit()
        logger.info("Beta snapshots captured: %d for report %d", len(snapshot_ids), report_id)
    return snapshot_ids


def capture_signal_snapshot(
    db: Session,
    stock_code: str,
    stock_name: str,
    snapshot_date: str,
    features: dict,
    strategy_family: str | None = None,
) -> int | None:
    """Lightweight snapshot for the signal pipeline (beta_scorer).

    Reuses already-computed beta context from score_and_create_plans()
    and supplements with ML features for XGBoost training.
    Does NOT commit — caller handles the transaction.

    Returns snapshot ID or None on failure.
    """
    try:
        stock = _get_stock(db, stock_code)
        valuation = _get_latest_valuation(db, stock_code, snapshot_date)
        ml_features = _compute_ml_features(db, stock_code, snapshot_date, valuation)

        snap = BetaSnapshot(
            stock_code=stock_code,
            stock_name=stock_name,
            snapshot_date=snapshot_date,
            market_regime=features.get("regime_code"),
            market_sentiment=features.get("market_sentiment"),
            industry=stock.industry if stock else None,
            sector_heat_score=features.get("sector_heat_score"),
            pe=features.get("pe") or (valuation.pe if valuation else None),
            pb=valuation.pb if valuation else None,
            market_cap=valuation.total_mv if valuation else None,
            turnover_rate=features.get("turnover_rate") or (valuation.turnover_rate if valuation else None),
            action="buy",
            alpha_score=features.get("alpha_score"),
            final_score=features.get("alpha_score"),
            strategy_family=strategy_family,
            entry_price=ml_features.get("entry_price"),
            day_of_week=ml_features.get("day_of_week"),
            stock_return_5d=ml_features.get("stock_return_5d"),
            stock_volatility_20d=ml_features.get("stock_volatility_20d"),
            volume_ratio_5d=ml_features.get("volume_ratio_5d"),
            index_return_5d=ml_features.get("index_return_5d"),
            index_return_20d=ml_features.get("index_return_20d"),
        )
        db.add(snap)
        db.flush()
        return snap.id
    except Exception as e:
        logger.warning("Signal snapshot failed for %s: %s", stock_code, e)
        return None


# ── Stage 2: Review ──────────────────────────────────────

_BETA_REVIEW_PROMPT = """\
你是交易复盘分析师。分析以下已完成交易中"Beta因子"(非技术面因素)的预测准确性。

交易概况:
- 股票: {stock_code} {stock_name}
- 买入日期: {buy_date}, 卖出日期: {sell_date}
- 持有天数: {hold_days}, 收益率: {pnl_pct:.2f}%
- 退出原因: {exit_reason}

买入时Beta因子快照:
- 市场环境: {regime} (置信度{regime_conf:.0f}%)
- 市场情绪: {market_sentiment}
- 个股情绪: {stock_sentiment}
- 所属行业: {industry}
- 板块热度: {sector_heat} (趋势: {sector_trend})
- PE: {pe}, PB: {pb}, 换手率: {turnover}%
- 活跃事件: {events}
- AI买入理由: {ai_reasoning}

请评估每个因子对交易结果的预测准确性:
- -1 = 误导(因子暗示应该赚钱但亏了，或反之)
- 0 = 中性(因子对结果无明显影响)
- +1 = 准确(因子正确预测了交易方向)

输出严格JSON(不要markdown):
{{
  "regime": {{"score": <-1|0|1>, "note": "一句话说明"}},
  "sentiment": {{"score": <-1|0|1>, "note": "一句话说明"}},
  "sector_heat": {{"score": <-1|0|1>, "note": "一句话说明"}},
  "news_events": {{"score": <-1|0|1>, "note": "一句话说明"}},
  "valuation": {{"score": <-1|0|1>, "note": "一句话说明"}},
  "key_lesson": "一句话核心教训(最多100字)"
}}"""


def create_beta_review(db: Session, review) -> Optional[BetaReview]:
    """Create beta factor review for a completed trade.

    Always creates a basic BetaReview with is_profitable (for XGBoost training).
    DeepSeek factor evaluation is attempted but failure is non-fatal.
    Does NOT commit — caller handles the transaction.
    """
    # Find entry snapshot — window match (snapshot at signal T, buy at T+1)
    window_start = review.first_buy_date
    try:
        from datetime import date as _d
        buy_d = _d.fromisoformat(review.first_buy_date)
        window_start = (buy_d - timedelta(days=3)).isoformat()
    except (ValueError, TypeError):
        pass

    entry_snap = (
        db.query(BetaSnapshot)
        .filter(
            BetaSnapshot.stock_code == review.stock_code,
            BetaSnapshot.snapshot_date >= window_start,
            BetaSnapshot.snapshot_date <= review.first_buy_date,
            BetaSnapshot.action == "buy",
        )
        .order_by(BetaSnapshot.snapshot_date.desc())
        .first()
    )
    if not entry_snap:
        logger.info("No beta snapshot for %s near %s — skipping beta review",
                     review.stock_code, review.first_buy_date)
        return None

    # Infer exit reason from trades
    exit_reason = "unknown"
    if review.trades:
        trades_list = review.trades if isinstance(review.trades, list) else []
        sells = [t for t in trades_list if t.get("action") in ("sell", "reduce")]
        if sells:
            exit_reason = sells[-1].get("sell_reason", "ai_recommend") or "ai_recommend"

    is_profitable = review.pnl_pct > 0 if review.pnl_pct is not None else None

    # Create basic review (always succeeds — XGBoost only needs this)
    beta_review = BetaReview(
        review_id=review.id,
        stock_code=review.stock_code,
        pnl_pct=review.pnl_pct,
        holding_days=review.holding_days,
        exit_reason=exit_reason,
        entry_snapshot_id=entry_snap.id,
        is_profitable=is_profitable,
    )
    db.add(beta_review)
    db.flush()

    # Try DeepSeek factor evaluation (non-fatal — enriches review but not required)
    try:
        prompt = _BETA_REVIEW_PROMPT.format(
            stock_code=review.stock_code,
            stock_name=review.stock_name,
            buy_date=review.first_buy_date,
            sell_date=review.last_sell_date,
            hold_days=review.holding_days,
            pnl_pct=review.pnl_pct,
            exit_reason=exit_reason,
            regime=entry_snap.market_regime or "unknown",
            regime_conf=(entry_snap.market_regime_confidence or 0) * 100,
            market_sentiment=entry_snap.market_sentiment or "N/A",
            stock_sentiment=entry_snap.stock_sentiment or "N/A",
            industry=entry_snap.industry or "unknown",
            sector_heat=entry_snap.sector_heat_score or "N/A",
            sector_trend=entry_snap.sector_trend or "flat",
            pe=entry_snap.pe or "N/A",
            pb=entry_snap.pb or "N/A",
            turnover=entry_snap.turnover_rate or "N/A",
            events=json.dumps(entry_snap.active_events or [], ensure_ascii=False)[:500],
            ai_reasoning=(entry_snap.ai_reasoning or "")[:300],
        )
        result = _call_deepseek(prompt)
        if result:
            beta_review.regime_accuracy = result.get("regime", {}).get("score", 0)
            beta_review.sentiment_accuracy = result.get("sentiment", {}).get("score", 0)
            beta_review.sector_heat_accuracy = result.get("sector_heat", {}).get("score", 0)
            beta_review.news_event_accuracy = result.get("news_events", {}).get("score", 0)
            beta_review.valuation_accuracy = result.get("valuation", {}).get("score", 0)
            beta_review.factor_details = result
            beta_review.key_lesson = result.get("key_lesson", "")
    except Exception as e:
        logger.warning("DeepSeek beta review failed for %s (non-fatal): %s", review.stock_code, e)

    logger.info("Beta review: %s pnl=%.1f%% profitable=%s",
                review.stock_code, review.pnl_pct, is_profitable)
    return beta_review


# ── Stage 3: Aggregate ──────────────────────────────────

def aggregate_beta_insights(db: Session, min_samples: int = 3) -> int:
    """Aggregate beta reviews into reusable insights by dimension.

    Groups reviews by market_regime, industry, and regime+sentiment combo.
    Returns count of insights created/updated.
    """
    reviews = db.query(BetaReview).all()
    if len(reviews) < min_samples:
        logger.info("Only %d beta reviews — need at least %d for aggregation", len(reviews), min_samples)
        return 0

    snap_ids = [r.entry_snapshot_id for r in reviews if r.entry_snapshot_id]
    snapshots = {
        s.id: s
        for s in db.query(BetaSnapshot).filter(BetaSnapshot.id.in_(snap_ids)).all()
    } if snap_ids else {}

    insights_created = 0

    # Group by market regime
    regime_groups = defaultdict(list)
    for r in reviews:
        snap = snapshots.get(r.entry_snapshot_id)
        if snap and snap.market_regime:
            regime_groups[snap.market_regime].append(r)
    for regime, group in regime_groups.items():
        if len(group) >= min_samples:
            _upsert_insight(db, "regime_pattern", regime, group)
            insights_created += 1

    # Group by industry
    industry_groups = defaultdict(list)
    for r in reviews:
        snap = snapshots.get(r.entry_snapshot_id)
        if snap and snap.industry:
            industry_groups[snap.industry].append(r)
    for ind, group in industry_groups.items():
        if len(group) >= min_samples:
            _upsert_insight(db, "sector_pattern", ind, group)
            insights_created += 1

    # Group by regime + sentiment combo
    combo_groups = defaultdict(list)
    for r in reviews:
        snap = snapshots.get(r.entry_snapshot_id)
        if snap and snap.market_regime and snap.market_sentiment is not None:
            sent_label = (
                "positive" if snap.market_sentiment > 20
                else "negative" if snap.market_sentiment < -20
                else "neutral"
            )
            combo_groups[f"{snap.market_regime}+{sent_label}_sentiment"].append(r)
    for combo, group in combo_groups.items():
        if len(group) >= min_samples:
            _upsert_insight(db, "combination_pattern", combo, group)
            insights_created += 1

    db.commit()
    logger.info("Beta aggregation complete: %d insights from %d reviews", insights_created, len(reviews))
    return insights_created


# ── Stage 4: Scorecard ───────────────────────────────────

def compute_beta_scorecard(db: Session, stock_codes: list[str]) -> dict:
    """Compute beta scorecard for a list of candidate stocks.

    For each stock, looks up current context and matches against
    accumulated beta insights to produce a structured scorecard.
    """
    if not stock_codes:
        return {}

    insights = db.query(BetaInsight).filter(BetaInsight.sample_count >= 3).all()
    if not insights:
        return {code: _empty_scorecard(code) for code in stock_codes}

    # Index insights by type+dimension
    insight_map = {}
    for ins in insights:
        insight_map[(ins.insight_type, ins.dimension)] = ins

    result = {}
    for code in stock_codes:
        stock = _get_stock(db, code)
        concepts = _get_stock_concepts(db, code)
        industry = stock.industry if stock else ""

        factors = {}
        risk_flags = []

        # Sector pattern
        sec_insight = insight_map.get(("sector_pattern", industry))
        if sec_insight:
            factors["sector_heat"] = {
                "industry": industry,
                "historical_win_rate": round(sec_insight.win_rate, 2),
                "avg_pnl": round(sec_insight.avg_pnl_pct, 2),
                "samples": sec_insight.sample_count,
            }
            if sec_insight.win_rate < 0.4:
                risk_flags.append(f"{industry}行业历史胜率仅{sec_insight.win_rate:.0%}")

        # Regime pattern (use latest regime)
        regime = _get_current_regime(db, datetime.now().strftime("%Y-%m-%d"))
        if regime:
            reg_insight = insight_map.get(("regime_pattern", regime.regime))
            if reg_insight:
                factors["regime_match"] = {
                    "current_regime": regime.regime,
                    "historical_win_rate": round(reg_insight.win_rate, 2),
                    "avg_pnl": round(reg_insight.avg_pnl_pct, 2),
                    "samples": reg_insight.sample_count,
                }

        # Valuation context
        valuation = _get_latest_valuation(db, code, datetime.now().strftime("%Y-%m-%d"))
        if valuation and valuation.pe:
            factors["valuation"] = {"pe": round(valuation.pe, 1), "pb": round(valuation.pb or 0, 2)}
            if valuation.pe > 50:
                risk_flags.append(f"PE={valuation.pe:.0f}（高估值风险）")

        # Sentiment context
        market_sent = _get_latest_market_sentiment(db)
        if market_sent:
            factors["sentiment"] = {
                "market_sentiment": round(market_sent.market_sentiment, 1),
                "confidence": round(market_sent.confidence, 1),
            }

        # Compute composite beta_score
        beta_score = _compute_beta_score(factors)

        result[code] = {
            "stock_name": stock.name if stock else "",
            "industry": industry,
            "concepts": concepts[:5],
            "factors": factors,
            "beta_score": beta_score,
            "risk_flags": risk_flags,
        }

    return result


def _compute_beta_score(factors: dict) -> int:
    """Compute composite beta score (0-100) from factor insights."""
    scores = []

    sh = factors.get("sector_heat", {})
    if sh.get("samples", 0) >= 3:
        scores.append((sh["historical_win_rate"] * 100, 0.30))

    rm = factors.get("regime_match", {})
    if rm.get("samples", 0) >= 3:
        scores.append((rm["historical_win_rate"] * 100, 0.30))

    sent = factors.get("sentiment", {})
    if sent.get("confidence", 0) > 0:
        # Map -100..+100 sentiment to 0..100 scale
        sent_score = (sent["market_sentiment"] + 100) / 2
        scores.append((sent_score, 0.20))

    val = factors.get("valuation", {})
    if val.get("pe"):
        # Lower PE = higher safety score
        pe_score = max(0, min(100, 100 - val["pe"]))
        scores.append((pe_score, 0.20))

    if not scores:
        return 50  # No data -> neutral

    total_weight = sum(w for _, w in scores)
    return round(sum(s * w / total_weight for s, w in scores))


def _empty_scorecard(code: str) -> dict:
    return {
        "stock_name": "",
        "industry": "",
        "concepts": [],
        "factors": {},
        "beta_score": 50,
        "risk_flags": [],
    }


# ── Data helpers (query existing tables) ─────────────────

def _get_stock(db: Session, code: str):
    from api.models.stock import Stock
    return db.query(Stock).filter(Stock.code == code).first()


def _get_stock_concepts(db: Session, code: str) -> list[str]:
    from api.models.stock import StockConcept
    rows = db.query(StockConcept.concept_name).filter(StockConcept.stock_code == code).all()
    return [r[0] for r in rows]


def _get_current_regime(db: Session, report_date: str):
    from api.models.market_regime import MarketRegimeLabel
    from datetime import date as _date
    try:
        d = _date.fromisoformat(report_date)
    except ValueError:
        return None
    return (
        db.query(MarketRegimeLabel)
        .filter(MarketRegimeLabel.week_end >= d)
        .order_by(MarketRegimeLabel.week_end.desc())
        .first()
    )


def _get_latest_market_sentiment(db: Session):
    from api.models.news_sentiment import NewsSentimentResult
    return (
        db.query(NewsSentimentResult)
        .order_by(NewsSentimentResult.analysis_time.desc())
        .first()
    )


def _get_stock_sentiment(db: Session, code: str):
    from api.models.news_sentiment import StockNewsSentiment
    return (
        db.query(StockNewsSentiment)
        .filter(StockNewsSentiment.stock_code == code)
        .order_by(StockNewsSentiment.analysis_time.desc())
        .first()
    )


def _get_sector_heat(db: Session, industry: str, concepts: list[str]):
    """Find most recent sector heat for the stock's industry or concepts."""
    from api.models.news_agent import SectorHeat
    names = [industry] + concepts if industry else concepts
    if not names:
        return None
    return (
        db.query(SectorHeat)
        .filter(SectorHeat.sector_name.in_(names))
        .order_by(SectorHeat.snapshot_time.desc())
        .first()
    )


def _get_latest_valuation(db: Session, code: str, report_date: str):
    from api.models.stock import DailyBasic
    return (
        db.query(DailyBasic)
        .filter(DailyBasic.stock_code == code)
        .order_by(DailyBasic.trade_date.desc())
        .first()
    )


def _get_active_events(db: Session, code: str, industry: str, report_date: str) -> list[dict]:
    """Get recent news events affecting this stock or its sector."""
    from api.models.news_agent import NewsEvent
    cutoff = datetime.now() - timedelta(hours=48)
    events = (
        db.query(NewsEvent)
        .filter(NewsEvent.created_at >= cutoff)
        .order_by(NewsEvent.created_at.desc())
        .limit(20)
        .all()
    )
    # Filter to events relevant to this stock or industry
    relevant = []
    for e in events:
        affected_codes = e.affected_codes or []
        affected_sectors = e.affected_sectors or []
        if code in affected_codes or industry in affected_sectors:
            relevant.append({
                "event_type": e.event_type,
                "impact_level": e.impact_level,
                "impact_direction": e.impact_direction,
                "summary": (e.summary or "")[:200],
            })
    return relevant[:5]


def _compute_ml_features(db: Session, code: str, report_date: str, valuation) -> dict:
    """Compute ML feature columns for a beta snapshot."""
    from api.models.stock import DailyPrice, IndexDaily
    import numpy as np

    features: dict = {"day_of_week": datetime.now().weekday()}

    try:
        # Get recent stock prices (most recent 21 trading days)
        prices = (
            db.query(DailyPrice)
            .filter(DailyPrice.stock_code == code, DailyPrice.trade_date <= report_date)
            .order_by(DailyPrice.trade_date.desc())
            .limit(21)
            .all()
        )

        if prices:
            features["entry_price"] = prices[0].close * (prices[0].adj_factor or 1.0)

            if len(prices) >= 6:
                _c0 = prices[0].close * (prices[0].adj_factor or 1.0)
                _c5 = prices[5].close * (prices[5].adj_factor or 1.0)
                ret_5d = (_c0 - _c5) / _c5 * 100
                features["stock_return_5d"] = round(ret_5d, 4)

                avg_vol_5 = sum(p.volume for p in prices[:5]) / 5
                prev_avg = sum(p.volume for p in prices[1:6]) / 5
                features["volume_ratio_5d"] = round(avg_vol_5 / prev_avg, 4) if prev_avg > 0 else None

            if len(prices) >= 21:
                returns = [
                    (prices[i].close * (prices[i].adj_factor or 1.0) - prices[i + 1].close * (prices[i + 1].adj_factor or 1.0)) / (prices[i + 1].close * (prices[i + 1].adj_factor or 1.0))
                    for i in range(20)
                    if prices[i + 1].close > 0
                ]
                if returns:
                    features["stock_volatility_20d"] = round(float(np.std(returns)) * 100, 4)

        # Get index returns (上证指数 — try both "000001.SH" and "000001")
        idx_prices = (
            db.query(IndexDaily)
            .filter(IndexDaily.index_code == "000001.SH", IndexDaily.trade_date <= report_date)
            .order_by(IndexDaily.trade_date.desc())
            .limit(21)
            .all()
        )
        if not idx_prices:
            idx_prices = (
                db.query(IndexDaily)
                .filter(IndexDaily.index_code == "000001", IndexDaily.trade_date <= report_date)
                .order_by(IndexDaily.trade_date.desc())
                .limit(21)
                .all()
            )

        if idx_prices and len(idx_prices) >= 6:
            idx_ret_5d = (idx_prices[0].close - idx_prices[5].close) / idx_prices[5].close * 100
            features["index_return_5d"] = round(idx_ret_5d, 4)

        if idx_prices and len(idx_prices) >= 21:
            idx_ret_20d = (idx_prices[0].close - idx_prices[20].close) / idx_prices[20].close * 100
            features["index_return_20d"] = round(idx_ret_20d, 4)

    except Exception as e:
        logger.warning("ML feature computation failed for %s: %s", code, e)

    return features


def _upsert_insight(db: Session, insight_type: str, dimension: str, reviews: list[BetaReview]):
    """Create or update a single beta insight from a group of reviews."""
    existing = (
        db.query(BetaInsight)
        .filter(BetaInsight.insight_type == insight_type, BetaInsight.dimension == dimension)
        .first()
    )

    avg_pnl = sum(r.pnl_pct for r in reviews) / len(reviews)
    win_rate = sum(1 for r in reviews if r.pnl_pct > 0) / len(reviews)

    factor_scores = []
    for r in reviews:
        for acc in [r.regime_accuracy, r.sentiment_accuracy, r.sector_heat_accuracy,
                    r.news_event_accuracy, r.valuation_accuracy]:
            if acc is not None:
                factor_scores.append(acc)
    avg_accuracy = sum(factor_scores) / len(factor_scores) if factor_scores else 0.0

    text = (
        f"{dimension}: {len(reviews)}笔交易, 胜率{win_rate:.0%}, "
        f"平均收益{avg_pnl:+.1f}%, 因子准确度{avg_accuracy:+.2f}"
    )

    if existing:
        existing.sample_count = len(reviews)
        existing.avg_pnl_pct = round(avg_pnl, 2)
        existing.win_rate = round(win_rate, 4)
        existing.avg_factor_accuracy = round(avg_accuracy, 2)
        existing.insight_text = text
        existing.source_review_ids = [r.id for r in reviews]
        existing.last_updated = datetime.now()
    else:
        db.add(BetaInsight(
            insight_type=insight_type,
            dimension=dimension,
            sample_count=len(reviews),
            avg_pnl_pct=round(avg_pnl, 2),
            win_rate=round(win_rate, 4),
            avg_factor_accuracy=round(avg_accuracy, 2),
            insight_text=text,
            source_review_ids=[r.id for r in reviews],
        ))


def _call_deepseek(user_prompt: str) -> Optional[dict]:
    """Call DeepSeek API for beta factor evaluation."""
    try:
        from openai import OpenAI
        from api.config import get_settings; settings = get_settings()
        from api.utils.network import no_proxy

        client = OpenAI(
            api_key=settings.deepseek.api_key,
            base_url=settings.deepseek.base_url,
        )

        system = "你是交易因子分析师。严格输出JSON，不要markdown。"
        with no_proxy():
            response = client.chat.completions.create(
                model=settings.deepseek.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1000,
            )
        content = response.choices[0].message.content
        if not content:
            return None
        return json.loads(content)
    except Exception as e:
        logger.error("DeepSeek beta review call failed: %s", e)
        return None
