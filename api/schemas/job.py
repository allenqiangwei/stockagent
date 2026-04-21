"""Pydantic schemas for Job/Event API responses."""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: int
    job_type: str
    status: str
    title: str
    ref_type: Optional[str] = None
    ref_id: Optional[int] = None
    progress_pct: int = 0
    progress_message: Optional[str] = None
    queued_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    triggered_by: Optional[str] = None


class JobEventResponse(BaseModel):
    id: int
    job_id: int
    seq: int
    event_type: str
    payload: Optional[Any] = None
    created_at: datetime


class JobSummary(BaseModel):
    """Compact job info for overview / listing."""
    id: int
    job_type: str
    status: str
    title: str
    progress_pct: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
