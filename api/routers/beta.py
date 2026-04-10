"""Beta factor router — snapshots, reviews, insights, scorecard, and ML model."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.beta_factor import BetaSnapshot, BetaReview, BetaInsight, BetaDailyTrack, BetaModelState
from api.schemas.beta import BetaSnapshotItem, BetaReviewItem, BetaInsightItem

router = APIRouter(prefix="/api/beta", tags=["beta-factor"])


@router.get("/snapshots", response_model=list[BetaSnapshotItem])
def list_snapshots(
    stock_code: str = Query("", description="Filter by stock code"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List beta factor snapshots."""
    q = db.query(BetaSnapshot)
    if stock_code:
        q = q.filter(BetaSnapshot.stock_code == stock_code)
    rows = q.order_by(BetaSnapshot.created_at.desc()).limit(limit).all()
    return [
        BetaSnapshotItem(
            id=s.id, stock_code=s.stock_code, stock_name=s.stock_name,
            snapshot_date=s.snapshot_date, report_id=s.report_id,
            market_regime=s.market_regime, market_sentiment=s.market_sentiment,
            industry=s.industry, concepts=s.concepts,
            sector_heat_score=s.sector_heat_score, sector_trend=s.sector_trend,
            pe=s.pe, pb=s.pb,
            action=s.action, alpha_score=s.alpha_score,
            ai_reasoning=s.ai_reasoning,
        )
        for s in rows
    ]


@router.get("/reviews", response_model=list[BetaReviewItem])
def list_reviews(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List beta factor reviews."""
    rows = db.query(BetaReview).order_by(BetaReview.created_at.desc()).limit(limit).all()
    return [
        BetaReviewItem(
            id=r.id, review_id=r.review_id, stock_code=r.stock_code,
            pnl_pct=r.pnl_pct, holding_days=r.holding_days,
            exit_reason=r.exit_reason,
            regime_accuracy=r.regime_accuracy,
            sentiment_accuracy=r.sentiment_accuracy,
            sector_heat_accuracy=r.sector_heat_accuracy,
            news_event_accuracy=r.news_event_accuracy,
            valuation_accuracy=r.valuation_accuracy,
            key_lesson=r.key_lesson,
            factor_details=r.factor_details,
        )
        for r in rows
    ]


@router.get("/insights/active", response_model=list[BetaInsightItem])
def get_active_insights(
    regime: str = Query("", description="Filter by current regime"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Return actionable beta insights for AI analysis."""
    q = db.query(BetaInsight).filter(BetaInsight.sample_count >= 3)
    if regime:
        from sqlalchemy import or_
        q = q.filter(
            or_(
                BetaInsight.dimension.contains(regime),
                BetaInsight.insight_type == "combination_pattern",
            )
        )
    rows = q.order_by(BetaInsight.sample_count.desc()).limit(limit).all()
    return [
        BetaInsightItem(
            insight_type=i.insight_type, dimension=i.dimension,
            sample_count=i.sample_count, avg_pnl_pct=i.avg_pnl_pct,
            win_rate=i.win_rate, avg_factor_accuracy=i.avg_factor_accuracy,
            insight_text=i.insight_text,
        )
        for i in rows
    ]


@router.post("/insights/aggregate")
def trigger_aggregation(db: Session = Depends(get_db)):
    """Manually trigger beta insight aggregation from accumulated reviews."""
    from api.services.beta_engine import aggregate_beta_insights
    count = aggregate_beta_insights(db)
    return {"insights_updated": count}


@router.get("/scorecard")
def get_scorecard(
    stock_codes: str = Query(..., description="Comma-separated stock codes"),
    db: Session = Depends(get_db),
):
    """Compute beta scorecard for candidate stocks.

    Used by Claude AI during analysis to get structured non-technical factor data.
    """
    from api.services.beta_engine import compute_beta_scorecard
    codes = [c.strip() for c in stock_codes.split(",") if c.strip()]
    if not codes:
        return {}
    return compute_beta_scorecard(db, codes)


# ── Beta ML Overlay endpoints ────────────────────────────


@router.get("/model/status")
def get_model_status(db: Session = Depends(get_db)):
    """Get current Beta ML model status and metrics."""
    from api.services.beta_ml import get_active_model, FEATURE_NAMES

    model = get_active_model(db)

    # Count training data
    n_reviews = db.query(BetaReview).filter(BetaReview.is_profitable.isnot(None)).count()

    phase = "cold" if n_reviews < 30 else ("warm" if n_reviews < 100 else "mature")

    if not model:
        return {
            "has_model": False,
            "phase": phase,
            "training_samples": n_reviews,
            "message": f"No trained model. {n_reviews} reviews available ({30 - n_reviews} more needed)."
            if n_reviews < 30
            else f"{n_reviews} reviews available — ready for training.",
        }

    return {
        "has_model": True,
        "version": model.version,
        "phase": phase,
        "model_type": model.model_type,
        "training_samples": model.training_samples,
        "auc_score": model.auc_score,
        "accuracy": model.accuracy,
        "training_window": f"{model.training_window_start} ~ {model.training_window_end}",
        "feature_importance": model.feature_importance,
        "created_at": model.created_at.isoformat() if model.created_at else None,
        "available_reviews": n_reviews,
    }


@router.post("/model/train")
def trigger_training(force: bool = Query(False), db: Session = Depends(get_db)):
    """Manually trigger Beta ML model training."""
    from api.services.beta_ml import train_model
    result = train_model(db, force=force)
    return result


@router.get("/tracks")
def list_daily_tracks(
    holding_id: int = Query(0, description="Filter by holding ID"),
    stock_code: str = Query("", description="Filter by stock code"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List beta daily tracking records."""
    q = db.query(BetaDailyTrack)
    if holding_id:
        q = q.filter(BetaDailyTrack.holding_id == holding_id)
    if stock_code:
        q = q.filter(BetaDailyTrack.stock_code == stock_code)
    rows = q.order_by(BetaDailyTrack.track_date.desc()).limit(limit).all()
    return [
        {
            "id": t.id,
            "holding_id": t.holding_id,
            "stock_code": t.stock_code,
            "track_date": t.track_date,
            "close_price": t.close_price,
            "daily_return_pct": t.daily_return_pct,
            "cumulative_pnl_pct": t.cumulative_pnl_pct,
            "volume": t.volume,
            "volume_ratio": t.volume_ratio,
            "regime_code": t.regime_code,
            "sector_heat_score": t.sector_heat_score,
            "index_close": t.index_close,
            "news_event_count": t.news_event_count,
        }
        for t in rows
    ]


@router.get("/plans/ranked")
def get_ranked_plans(
    plan_date: str = Query("", description="Plan date (YYYY-MM-DD), defaults to today"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Get Beta-scored trade plans ranked by combined_score.

    Returns top plans for display — the 'Top 5-10' the user sees.
    """
    from api.models.bot_trading import BotTradePlan
    from datetime import datetime as _dt

    if not plan_date:
        plan_date = _dt.now().strftime("%Y-%m-%d")

    plans = (
        db.query(BotTradePlan)
        .filter(
            BotTradePlan.plan_date == plan_date,
            BotTradePlan.direction == "buy",
            BotTradePlan.combined_score.isnot(None),
        )
        .order_by(BotTradePlan.combined_score.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": p.id,
            "stock_code": p.stock_code,
            "stock_name": p.stock_name,
            "plan_price": p.plan_price,
            "quantity": p.quantity,
            "alpha_score": p.alpha_score,
            "beta_score": p.beta_score,
            "combined_score": p.combined_score,
            "status": p.status,
            "thinking": p.thinking,
            "source": p.source,
        }
        for p in plans
    ]


# ── Signal Grader ────────────────────────────────────────

@router.get("/signal-grader/calibration")
def get_signal_grader_calibration():
    """Get current signal grader calibration report (bin-level win rates)."""
    from api.services.signal_grader import get_calibration_report
    return get_calibration_report()


@router.post("/signal-grader/calibrate")
def trigger_calibration(db: Session = Depends(get_db)):
    """Manually trigger signal grader recalibration."""
    from api.services.signal_grader import calibrate
    return calibrate(db)


@router.get("/signal-grader/grade")
def grade_single_signal(
    alpha: float = Query(..., description="Alpha score (0-100)"),
    gamma: float = Query(None, description="Gamma score (0-100, optional)"),
    combined: float = Query(0.5, description="Combined score (0-1)"),
):
    """Grade a single signal combination."""
    from api.services.signal_grader import grade_signal
    return grade_signal(alpha, gamma, combined)


# ── Confidence Scorer ────────────────────────────────────────


@router.get("/confidence/model")
def get_confidence_model(db: Session = Depends(get_db)):
    """Get active confidence model report (version, AUC, Brier, coefficients)."""
    from api.services.confidence_scorer import get_model_report
    return get_model_report(db)


@router.post("/confidence/train")
def trigger_confidence_training(db: Session = Depends(get_db)):
    """Manually trigger confidence model training from historical trade data."""
    from api.services.confidence_scorer import train_confidence_model
    return train_confidence_model(db)


@router.get("/confidence/predict")
def predict_confidence_score(
    alpha: float = Query(..., description="Alpha score (0-100)"),
    gamma: float = Query(None, description="Gamma score (0-100, optional)"),
    trend_strength: float = Query(0.0, description="Market trend strength"),
    volatility: float = Query(0.0, description="Market volatility"),
    index_return_pct: float = Query(0.0, description="Weekly index return %"),
    db: Session = Depends(get_db),
):
    """Predict confidence score (0-100) for a signal with given features."""
    from api.services.confidence_scorer import predict_confidence
    score = predict_confidence(
        db, alpha, gamma,
        trend_strength=trend_strength,
        volatility=volatility,
        index_return_pct=index_return_pct,
    )
    return {"confidence": score}
