"""Artifacts router — list and inspect artifacts."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.models.artifact import Artifact
from api.models.base import get_db
from api.schemas.artifact import ArtifactResponse, ArtifactSummary

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("", response_model=list[ArtifactSummary])
def list_artifacts(
    artifact_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List artifacts with optional type filter."""
    q = db.query(Artifact)
    if artifact_type:
        q = q.filter(Artifact.artifact_type == artifact_type)
    artifacts = q.order_by(Artifact.created_at.desc()).limit(limit).all()
    return [
        ArtifactSummary(
            id=a.id,
            artifact_type=a.artifact_type,
            title=a.title,
            uri=a.uri,
            code_version=a.code_version,
            data_version=a.data_version,
            created_at=a.created_at,
        )
        for a in artifacts
    ]


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: int, db: Session = Depends(get_db)):
    """Get detailed artifact info including config snapshot."""
    a = db.query(Artifact).get(artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactResponse(
        id=a.id,
        artifact_type=a.artifact_type,
        uri=a.uri,
        content_hash=a.content_hash,
        job_id=a.job_id,
        producer=a.producer,
        code_version=a.code_version,
        data_version=a.data_version,
        config_hash=a.config_hash,
        config_snapshot=a.config_snapshot,
        title=a.title,
        size_bytes=a.size_bytes,
        metadata=a.metadata_,
        created_at=a.created_at,
    )
