"""News signals router — news-driven signals, events, sector heat."""

import logging
import threading
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from api.models.base import get_db, SessionLocal
from api.models.news_agent import NewsEvent, SectorHeat, NewsSignal, AgentRunLog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/news-signals", tags=["news-signals"])

_analysis_jobs: dict[str, dict] = {}


@router.get("/today")
def get_today_signals(
    date_str: str = Query("", alias="date"),
    db: Session = Depends(get_db),
):
    """Get news-driven signals for a date (default today)."""
    target = date_str or date.today().isoformat()
    rows = (
        db.query(NewsSignal)
        .filter(NewsSignal.trade_date == target)
        .order_by(NewsSignal.confidence.desc())
        .all()
    )
    return {
        "date": target,
        "count": len(rows),
        "signals": [
            {
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "action": r.action,
                "signal_source": r.signal_source,
                "confidence": r.confidence,
                "reason": r.reason,
                "sector_name": r.sector_name,
                "created_at": r.created_at.strftime("%H:%M") if r.created_at else "",
            }
            for r in rows
        ],
    }


@router.get("/history")
def get_signal_history(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    action: str = Query(""),
    db: Session = Depends(get_db),
):
    """Paginated news signal history."""
    q = db.query(NewsSignal).order_by(NewsSignal.created_at.desc())
    if action:
        q = q.filter(NewsSignal.action == action)
    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    return {
        "page": page,
        "size": size,
        "total": total,
        "items": [
            {
                "id": r.id,
                "trade_date": r.trade_date,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "action": r.action,
                "signal_source": r.signal_source,
                "confidence": r.confidence,
                "reason": r.reason,
                "sector_name": r.sector_name,
            }
            for r in rows
        ],
    }


@router.get("/sectors")
def get_sector_heat(
    date_str: str = Query("", alias="date"),
    db: Session = Depends(get_db),
):
    """Get latest sector heat rankings."""
    if date_str:
        cutoff = datetime.strptime(date_str, "%Y-%m-%d")
        end = cutoff + timedelta(days=1)
    else:
        end = datetime.now()
        cutoff = end - timedelta(hours=24)

    rows = (
        db.query(SectorHeat)
        .filter(SectorHeat.snapshot_time >= cutoff, SectorHeat.snapshot_time < end)
        .order_by(SectorHeat.heat_score.desc())
        .all()
    )
    return {
        "count": len(rows),
        "sectors": [
            {
                "id": r.id,
                "sector_name": r.sector_name,
                "sector_type": r.sector_type,
                "heat_score": r.heat_score,
                "trend": r.trend,
                "news_count": r.news_count,
                "top_stocks": r.top_stocks or [],
                "event_summary": r.event_summary,
                "snapshot_time": r.snapshot_time.strftime("%Y-%m-%d %H:%M") if r.snapshot_time else "",
            }
            for r in rows
        ],
    }


@router.get("/events")
def get_events(
    date_str: str = Query("", alias="date"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Get recent news events."""
    q = db.query(NewsEvent).order_by(NewsEvent.created_at.desc())
    if date_str:
        q = q.filter(NewsEvent.created_at >= date_str)
    rows = q.limit(limit).all()
    return {
        "count": len(rows),
        "events": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "impact_level": r.impact_level,
                "impact_direction": r.impact_direction,
                "affected_codes": r.affected_codes or [],
                "affected_sectors": r.affected_sectors or [],
                "summary": r.summary,
                "source_titles": r.source_titles or [],
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            }
            for r in rows
        ],
    }


@router.post("/analyze")
def trigger_analysis():
    """Manually trigger news agent pipeline (fire-and-forget)."""
    from api.services.news_agent_scheduler import get_news_agent_scheduler

    scheduler = get_news_agent_scheduler()
    if scheduler.is_busy:
        raise HTTPException(409, "Analysis already in progress")

    job_id = str(uuid.uuid4())[:8]
    _analysis_jobs[job_id] = {"status": "processing", "result": None, "error": None}

    def _run():
        try:
            db = SessionLocal()
            try:
                from api.services.news_agent_engine import NewsAgentEngine
                engine = NewsAgentEngine(db)
                result = engine.run_analysis("manual")
                _analysis_jobs[job_id] = {"status": "completed", "result": result, "error": None}
            finally:
                db.close()
        except Exception as e:
            logger.error("Manual news analysis failed: %s", e)
            _analysis_jobs[job_id] = {"status": "error", "result": None, "error": str(e)}

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "processing"}


@router.get("/analyze/poll")
def poll_analysis(job_id: str = Query(...)):
    """Poll analysis progress."""
    job = _analysis_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/runs")
def get_run_logs(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get recent agent run logs."""
    rows = (
        db.query(AgentRunLog)
        .order_by(AgentRunLog.run_time.desc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(rows),
        "runs": [
            {
                "id": r.id,
                "run_time": r.run_time.strftime("%Y-%m-%d %H:%M") if r.run_time else "",
                "period_type": r.period_type,
                "agent_name": r.agent_name,
                "input_news_count": r.input_news_count,
                "output_summary": r.output_summary,
                "duration_ms": r.duration_ms,
                "status": r.status,
            }
            for r in rows
        ],
    }
