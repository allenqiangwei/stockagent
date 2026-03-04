"""Beta factor router — snapshots, reviews, insights, and scorecard."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.beta_factor import BetaSnapshot, BetaReview, BetaInsight
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
