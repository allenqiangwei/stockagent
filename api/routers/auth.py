"""Auth router — manage API keys and view audit log."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import require_role
from api.models.auth import ApiKey, AuditLog
from api.models.base import get_db
from api.services.auth_service import generate_api_key, revoke_key

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str
    role: str = "readonly"


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    role: str
    is_active: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime


class CreateKeyResponse(ApiKeyResponse):
    raw_key: str  # Only shown once at creation time


class AuditLogEntry(BaseModel):
    id: int
    timestamp: datetime
    api_key_name: Optional[str] = None
    role: Optional[str] = None
    method: str
    path: str
    status_code: int
    ip_address: Optional[str] = None
    duration_ms: Optional[int] = None


# ── Endpoints ─────────────────────────────────

@router.post(
    "/keys",
    response_model=CreateKeyResponse,
    dependencies=[Depends(require_role("admin"))],
)
def create_key(body: CreateKeyRequest, db: Session = Depends(get_db)):
    """Create a new API key (admin only). The raw key is shown ONCE."""
    try:
        record, raw_key = generate_api_key(db, name=body.name, role=body.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return CreateKeyResponse(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        role=record.role,
        is_active=record.is_active,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
        raw_key=raw_key,
    )


@router.get(
    "/keys",
    response_model=list[ApiKeyResponse],
    dependencies=[Depends(require_role("admin"))],
)
def list_keys(db: Session = Depends(get_db)):
    """List all API keys (admin only). Raw keys are never returned."""
    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return [
        ApiKeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            role=k.role,
            is_active=k.is_active,
            last_used_at=k.last_used_at,
            created_at=k.created_at,
        )
        for k in keys
    ]


@router.delete(
    "/keys/{key_id}",
    dependencies=[Depends(require_role("admin"))],
)
def delete_key(key_id: int, db: Session = Depends(get_db)):
    """Revoke (deactivate) an API key (admin only)."""
    if not revoke_key(db, key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"status": "revoked"}


@router.get(
    "/audit-log",
    response_model=list[AuditLogEntry],
    dependencies=[Depends(require_role("admin"))],
)
def get_audit_log(
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """View recent audit log entries (admin only)."""
    since = datetime.utcnow() - timedelta(hours=hours)
    entries = (
        db.query(AuditLog)
        .filter(AuditLog.timestamp >= since)
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        AuditLogEntry(
            id=e.id,
            timestamp=e.timestamp,
            api_key_name=e.api_key_name,
            role=e.role,
            method=e.method,
            path=e.path,
            status_code=e.status_code,
            ip_address=e.ip_address,
            duration_ms=e.duration_ms,
        )
        for e in entries
    ]
