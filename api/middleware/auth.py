"""Authentication middleware — validates API key on every request."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.config import get_settings
from api.models.base import SessionLocal
from api.services.auth_service import validate_key

logger = logging.getLogger(__name__)

# Paths that never require auth
_PUBLIC_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc", "/metrics"}

# Hosts considered local (includes IPv4-mapped IPv6 from Next.js proxy)
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Extract and validate API key from Authorization header or X-API-Key."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public endpoints and OPTIONS (CORS preflight)
        if path in _PUBLIC_PATHS or request.method == "OPTIONS":
            request.state.role = "admin"  # public endpoints get full access
            request.state.api_key_id = None
            request.state.api_key_name = None
            return await call_next(request)

        # Check if auth is enabled
        settings = get_settings()
        if not settings.auth.enabled:
            request.state.role = "admin"
            request.state.api_key_id = None
            request.state.api_key_name = None
            return await call_next(request)

        # Bypass for localhost if configured
        if settings.auth.bypass_local:
            client_host = request.client.host if request.client else ""
            if client_host in _LOCAL_HOSTS:
                request.state.role = "admin"
                request.state.api_key_id = None
                request.state.api_key_name = "localhost"
                return await call_next(request)

        # Extract token from Authorization: Bearer <key> or X-API-Key: <key>
        raw_key = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            raw_key = auth_header[7:].strip()
        if not raw_key:
            raw_key = request.headers.get("x-api-key", "").strip()

        if not raw_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing API key. Use Authorization: Bearer <key> or X-API-Key header."},
            )

        # Validate against DB
        db = SessionLocal()
        try:
            api_key = validate_key(db, raw_key)
        finally:
            db.close()

        if not api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or revoked API key."},
            )

        # Store auth info on request state
        request.state.role = api_key.role
        request.state.api_key_id = api_key.id
        request.state.api_key_name = api_key.name

        return await call_next(request)
