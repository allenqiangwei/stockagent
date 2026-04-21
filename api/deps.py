"""Shared FastAPI dependencies for auth and common patterns."""

from fastapi import Depends, HTTPException, Request

from api.services.auth_service import has_permission


def get_current_role(request: Request) -> str:
    """Extract the current user's role from request state (set by auth middleware)."""
    return getattr(request.state, "role", "readonly")


def require_role(minimum_role: str):
    """Dependency factory: require at least the given role level.

    Usage: @router.post("/admin-only", dependencies=[Depends(require_role("admin"))])
    """
    def _check(request: Request):
        role = getattr(request.state, "role", "readonly")
        if not has_permission(role, minimum_role):
            raise HTTPException(
                status_code=403,
                detail=f"Requires '{minimum_role}' role. Your role: '{role}'.",
            )
        return role
    return _check
