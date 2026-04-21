"""Artifact service — register and query artifacts with lineage metadata."""

import hashlib
import json
import logging
import subprocess
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models.artifact import Artifact
from api.models.base import SessionLocal

logger = logging.getLogger(__name__)


def get_code_version() -> Optional[str]:
    """Get current git short hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def get_data_version(db: Session) -> Optional[str]:
    """Get latest daily price date as data version."""
    try:
        from api.models.stock import DailyPrice
        row = db.query(func.max(DailyPrice.trade_date)).scalar()
        if row:
            return row.isoformat() if hasattr(row, "isoformat") else str(row)
    except Exception:
        pass
    return None


def compute_config_hash(config: dict) -> str:
    """SHA-256 of deterministic JSON serialization."""
    canonical = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def register_artifact(
    db: Session,
    artifact_type: str,
    uri: str,
    title: str = "",
    producer: str = "",
    job_id: Optional[int] = None,
    config_snapshot: Optional[dict] = None,
    content_hash: Optional[str] = None,
    size_bytes: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> Artifact:
    """Register an artifact with full lineage metadata."""
    config_hash = compute_config_hash(config_snapshot) if config_snapshot else None

    artifact = Artifact(
        artifact_type=artifact_type,
        uri=uri,
        title=title,
        producer=producer,
        job_id=job_id,
        code_version=get_code_version(),
        data_version=get_data_version(db),
        config_hash=config_hash,
        config_snapshot=config_snapshot,
        content_hash=content_hash,
        size_bytes=size_bytes,
        metadata_=metadata,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    logger.info(
        "Artifact #%d registered: [%s] %s (code=%s, data=%s)",
        artifact.id, artifact_type, title,
        artifact.code_version, artifact.data_version,
    )
    return artifact
