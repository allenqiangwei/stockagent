"""Pydantic schemas for Artifact API."""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel


class ArtifactResponse(BaseModel):
    id: int
    artifact_type: str
    uri: str
    content_hash: Optional[str] = None
    job_id: Optional[int] = None
    producer: Optional[str] = None
    code_version: Optional[str] = None
    data_version: Optional[str] = None
    config_hash: Optional[str] = None
    config_snapshot: Optional[Any] = None
    title: Optional[str] = None
    size_bytes: Optional[int] = None
    metadata: Optional[Any] = None
    created_at: datetime


class ArtifactSummary(BaseModel):
    id: int
    artifact_type: str
    title: Optional[str] = None
    uri: str
    code_version: Optional[str] = None
    data_version: Optional[str] = None
    created_at: datetime
