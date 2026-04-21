"""Ops router — system overview and error summary."""

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models.base import get_db
from api.models.job import Job, JobEvent
from api.schemas.ops import OpsOverview
from api.schemas.job import JobSummary

router = APIRouter(prefix="/api/ops", tags=["ops"])

# Set at app startup
_startup_time: float = time.time()


def set_startup_time():
    global _startup_time
    _startup_time = time.time()


@router.get("/overview", response_model=OpsOverview)
def get_overview(db: Session = Depends(get_db)):
    """Single-call system overview. Target: <200ms."""
    now = datetime.utcnow()
    since_24h = now - timedelta(hours=24)

    # ── Schedulers ──────────────────────────────
    data_sync_status = {}
    try:
        from api.services.signal_scheduler import get_signal_scheduler
        data_sync_status = get_signal_scheduler().get_status()
    except Exception:
        data_sync_status = {"error": "unavailable"}

    news_agent_status = {}
    try:
        from api.services.news_agent_scheduler import get_news_agent_scheduler
        news_agent_status = get_news_agent_scheduler().get_status()
    except Exception:
        news_agent_status = {"error": "unavailable"}

    # ── Jobs ────────────────────────────────────
    running_jobs = (
        db.query(Job)
        .filter(Job.status == "running")
        .order_by(Job.started_at.desc())
        .limit(20)
        .all()
    )

    recent_failed = (
        db.query(Job)
        .filter(Job.status == "failed", Job.finished_at >= since_24h)
        .order_by(Job.finished_at.desc())
        .limit(10)
        .all()
    )

    # Job counts (24h)
    count_rows = (
        db.query(Job.status, func.count(Job.id))
        .filter(Job.queued_at >= since_24h, Job.status.in_(["succeeded", "failed", "canceled"]))
        .group_by(Job.status)
        .all()
    )
    job_counts = {status: cnt for status, cnt in count_rows}

    # ── Data freshness ──────────────────────────
    latest_price_date = None
    try:
        from api.models.stock import DailyPrice
        row = db.query(func.max(DailyPrice.trade_date)).scalar()
        if row:
            latest_price_date = row.isoformat() if hasattr(row, "isoformat") else str(row)
    except Exception:
        pass

    latest_report_date = None
    try:
        from api.models.ai_analyst import AIReport
        row = db.query(func.max(AIReport.trade_date)).scalar()
        if row:
            latest_report_date = str(row)
    except Exception:
        pass

    latest_news_time = None
    try:
        from api.models.news_agent import NewsEvent
        row = db.query(func.max(NewsEvent.published_at)).scalar()
        if row:
            latest_news_time = row.isoformat() if hasattr(row, "isoformat") else str(row)
    except Exception:
        pass

    # ── Strategy library ────────────────────────
    total_strategies = 0
    try:
        from api.models.strategy import Strategy
        total_strategies = db.query(func.count(Strategy.id)).scalar() or 0
    except Exception:
        pass

    total_experiments = 0
    total_rounds = 0
    try:
        from api.models.ai_lab import Experiment, ExplorationRound
        total_experiments = db.query(func.count(Experiment.id)).scalar() or 0
        total_rounds = db.query(func.count(ExplorationRound.id)).scalar() or 0
    except Exception:
        pass

    # ── Bot ──────────────────────────────────────
    bot_count = 0
    pending_plans = 0
    try:
        from api.models.bot_trading import BotPortfolio, BotTradePlan
        bot_count = db.query(func.count(BotPortfolio.id)).scalar() or 0
        pending_plans = (
            db.query(func.count(BotTradePlan.id))
            .filter(BotTradePlan.status == "pending")
            .scalar() or 0
        )
    except Exception:
        pass

    # ── Recent errors (from job events) ─────────
    recent_errors = []
    try:
        error_events = (
            db.query(JobEvent)
            .filter(JobEvent.event_type == "error", JobEvent.created_at >= since_24h)
            .order_by(JobEvent.created_at.desc())
            .limit(10)
            .all()
        )
        recent_errors = [
            {"job_id": e.job_id, "payload": e.payload, "time": e.created_at.isoformat()}
            for e in error_events
        ]
    except Exception:
        pass

    # ── Database health ─────────────────────────
    db_ok = True
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    return OpsOverview(
        uptime_seconds=round(time.time() - _startup_time, 1),
        version="2.0.0",
        database_ok=db_ok,
        data_sync=data_sync_status,
        news_agent=news_agent_status,
        running_jobs=[
            JobSummary(
                id=j.id, job_type=j.job_type, status=j.status,
                title=j.title, progress_pct=j.progress_pct,
                started_at=j.started_at, finished_at=j.finished_at,
            ) for j in running_jobs
        ],
        recent_failed_jobs=[
            JobSummary(
                id=j.id, job_type=j.job_type, status=j.status,
                title=j.title, progress_pct=j.progress_pct,
                started_at=j.started_at, finished_at=j.finished_at,
            ) for j in recent_failed
        ],
        job_counts_24h=job_counts,
        latest_daily_price_date=latest_price_date,
        latest_ai_report_date=latest_report_date,
        latest_news_event_time=latest_news_time,
        total_strategies=total_strategies,
        total_experiments=total_experiments,
        total_exploration_rounds=total_rounds,
        bot_portfolio_count=bot_count,
        pending_trade_plans=pending_plans,
        recent_errors=recent_errors,
    )
