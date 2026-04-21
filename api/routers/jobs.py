"""Jobs router — list, inspect, stream, and cancel jobs."""

import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.deps import require_role
from api.models.base import get_db
from api.models.job import Job, JobEvent
from api.schemas.job import JobResponse, JobEventResponse, JobSummary
from api.services.job_manager import get_job_manager

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobSummary])
def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    job_type: Optional[str] = Query(None, description="Filter by job_type"),
    hours: int = Query(48, ge=1, le=720, description="Look back N hours"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List jobs with optional filtering."""
    q = db.query(Job)
    since = datetime.utcnow() - timedelta(hours=hours)
    q = q.filter(Job.queued_at >= since)

    if status:
        q = q.filter(Job.status == status)
    if job_type:
        q = q.filter(Job.job_type == job_type)

    jobs = q.order_by(Job.queued_at.desc()).limit(limit).all()
    return [
        JobSummary(
            id=j.id,
            job_type=j.job_type,
            status=j.status,
            title=j.title,
            progress_pct=j.progress_pct,
            started_at=j.started_at,
            finished_at=j.finished_at,
        )
        for j in jobs
    ]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Get detailed job info."""
    job = db.query(Job).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        title=job.title,
        ref_type=job.ref_type,
        ref_id=job.ref_id,
        progress_pct=job.progress_pct,
        progress_message=job.progress_message,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_message=job.error_message,
        triggered_by=job.triggered_by,
    )


@router.get("/{job_id}/events", response_model=list[JobEventResponse])
def get_job_events(
    job_id: int,
    after_seq: int = Query(0, ge=0, description="Return events after this sequence number"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Get events for a job (paginated by sequence number)."""
    job = db.query(Job).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    events = (
        db.query(JobEvent)
        .filter(JobEvent.job_id == job_id, JobEvent.seq > after_seq)
        .order_by(JobEvent.seq)
        .limit(limit)
        .all()
    )
    return [
        JobEventResponse(
            id=e.id,
            job_id=e.job_id,
            seq=e.seq,
            event_type=e.event_type,
            payload=e.payload,
            created_at=e.created_at,
        )
        for e in events
    ]


@router.get("/{job_id}/stream")
def stream_job_events(job_id: int, db: Session = Depends(get_db)):
    """SSE stream of job events. Pushes new events as they arrive."""
    job = db.query(Job).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    def event_generator():
        last_seq = 0
        from api.models.base import SessionLocal
        import time

        while True:
            poll_db = SessionLocal()
            try:
                j = poll_db.query(Job).get(job_id)
                if not j:
                    break

                events = (
                    poll_db.query(JobEvent)
                    .filter(JobEvent.job_id == job_id, JobEvent.seq > last_seq)
                    .order_by(JobEvent.seq)
                    .limit(50)
                    .all()
                )

                for ev in events:
                    data = {
                        "seq": ev.seq,
                        "event_type": ev.event_type,
                        "payload": ev.payload,
                    }
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    last_seq = ev.seq

                # Send progress update
                yield f"data: {json.dumps({'type': 'progress', 'pct': j.progress_pct, 'message': j.progress_message})}\n\n"

                if j.status in ("succeeded", "failed", "canceled"):
                    yield f"data: {json.dumps({'type': 'done', 'status': j.status})}\n\n"
                    break
            finally:
                poll_db.close()

            time.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/{job_id}/cancel",
    dependencies=[Depends(require_role("operator"))],
)
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    """Cancel a queued or running job (operator+ only)."""
    mgr = get_job_manager()
    if not mgr.cancel(job_id, db=db):
        raise HTTPException(
            status_code=400,
            detail="Job cannot be canceled (not queued or running)",
        )
    return {"status": "cancel_requested", "job_id": job_id}
