"""Audit middleware — logs POST/PUT/DELETE requests to audit_log table."""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.models.auth import AuditLog
from api.models.base import SessionLocal

logger = logging.getLogger(__name__)

# Only audit mutating methods
_AUDITED_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


class AuditMiddleware(BaseHTTPMiddleware):
    """Record mutating API calls to audit_log after response completes."""

    async def dispatch(self, request: Request, call_next):
        if request.method not in _AUDITED_METHODS:
            return await call_next(request)

        # Capture request body preview (first 500 chars) for POST/PUT
        body_preview = None
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.body()
                body_preview = body.decode("utf-8", errors="replace")[:500]
            except Exception:
                body_preview = None

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        # Write audit log asynchronously (best-effort)
        try:
            db = SessionLocal()
            try:
                entry = AuditLog(
                    api_key_id=getattr(request.state, "api_key_id", None),
                    api_key_name=getattr(request.state, "api_key_name", None),
                    role=getattr(request.state, "role", None),
                    method=request.method,
                    path=str(request.url.path),
                    status_code=response.status_code,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent", "")[:500],
                    request_body_preview=body_preview,
                    duration_ms=duration_ms,
                )
                db.add(entry)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to write audit log: %s", e)

        return response
