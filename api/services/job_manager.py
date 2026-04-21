"""Job manager — create, update, and query jobs with thread-safe DB access.

Each method opens its own session so callers from background threads don't
need to pass one in. For request-scoped usage, pass an existing session.
"""

import logging
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from api.models.base import SessionLocal
from api.models.job import Job, JobEvent

logger = logging.getLogger(__name__)


class JobManager:
    """Thread-safe job lifecycle manager."""

    def __init__(self):
        self._seq_counters: dict[int, int] = {}
        self._lock = threading.Lock()
        # Cancel flags — checked by long-running jobs
        self._cancel_flags: dict[int, bool] = {}

    # ── Lifecycle ─────────────────────────────────

    def create(
        self,
        job_type: str,
        title: str,
        triggered_by: str = "system",
        ref_type: Optional[str] = None,
        ref_id: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> int:
        """Create a new job in 'queued' status. Returns job ID."""
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            job = Job(
                job_type=job_type,
                status="queued",
                title=title,
                triggered_by=triggered_by,
                ref_type=ref_type,
                ref_id=ref_id,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            with self._lock:
                self._seq_counters[job.id] = 0
            logger.info("Job #%d created: [%s] %s", job.id, job_type, title)
            return job.id
        finally:
            if own_db:
                db.close()

    def start(self, job_id: int, db: Optional[Session] = None):
        """Transition job from queued → running."""
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            job = db.query(Job).get(job_id)
            if job and job.status == "queued":
                job.status = "running"
                job.started_at = datetime.utcnow()
                db.commit()
        finally:
            if own_db:
                db.close()

    def update_progress(
        self,
        job_id: int,
        pct: int,
        message: str = "",
        db: Optional[Session] = None,
    ):
        """Update progress percentage and message."""
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            job = db.query(Job).get(job_id)
            if job and job.status == "running":
                job.progress_pct = min(pct, 100)
                job.progress_message = message[:500] if message else None
                db.commit()
        finally:
            if own_db:
                db.close()

    def succeed(
        self,
        job_id: int,
        message: str = "",
        db: Optional[Session] = None,
    ):
        """Mark job as succeeded."""
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            job = db.query(Job).get(job_id)
            if job and job.status in ("queued", "running"):
                job.status = "succeeded"
                job.progress_pct = 100
                job.progress_message = message[:500] if message else None
                job.finished_at = datetime.utcnow()
                db.commit()
                logger.info("Job #%d succeeded: %s", job_id, job.title)
        finally:
            if own_db:
                db.close()
            self._cleanup(job_id)

    def fail(
        self,
        job_id: int,
        error: str = "",
        db: Optional[Session] = None,
    ):
        """Mark job as failed."""
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            job = db.query(Job).get(job_id)
            if job and job.status in ("queued", "running"):
                job.status = "failed"
                job.error_message = error[:2000] if error else None
                job.finished_at = datetime.utcnow()
                db.commit()
                logger.warning("Job #%d failed: %s — %s", job_id, job.title, error[:200])
        finally:
            if own_db:
                db.close()
            self._cleanup(job_id)

    def cancel(self, job_id: int, db: Optional[Session] = None) -> bool:
        """Cancel a job. Queued → immediate cancel. Running → set flag."""
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            job = db.query(Job).get(job_id)
            if not job:
                return False
            if job.status == "queued":
                job.status = "canceled"
                job.finished_at = datetime.utcnow()
                db.commit()
                self._cleanup(job_id)
                return True
            if job.status == "running":
                with self._lock:
                    self._cancel_flags[job_id] = True
                return True
            return False
        finally:
            if own_db:
                db.close()

    def is_canceled(self, job_id: int) -> bool:
        """Check if cancel was requested (call from background threads)."""
        with self._lock:
            return self._cancel_flags.get(job_id, False)

    # ── Events ────────────────────────────────────

    def emit_event(
        self,
        job_id: int,
        event_type: str,
        payload: Optional[dict] = None,
        db: Optional[Session] = None,
    ):
        """Append an event to a job's event log."""
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            with self._lock:
                seq = self._seq_counters.get(job_id, 0) + 1
                self._seq_counters[job_id] = seq

            event = JobEvent(
                job_id=job_id,
                seq=seq,
                event_type=event_type,
                payload=payload,
            )
            db.add(event)
            db.commit()
        except Exception as e:
            logger.debug("Failed to emit job event: %s", e)
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            if own_db:
                db.close()

    # ── Internal ──────────────────────────────────

    def _cleanup(self, job_id: int):
        with self._lock:
            self._seq_counters.pop(job_id, None)
            self._cancel_flags.pop(job_id, None)


# Global singleton
_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
