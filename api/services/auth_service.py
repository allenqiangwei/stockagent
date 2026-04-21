"""Auth service — API key generation, validation, and management."""

import logging
import secrets
from datetime import datetime
from typing import Optional

import bcrypt
from sqlalchemy.orm import Session

from api.models.auth import ApiKey

logger = logging.getLogger(__name__)

# Role hierarchy: admin > operator > readonly
ROLE_HIERARCHY = {"admin": 3, "operator": 2, "readonly": 1}


def generate_api_key(
    db: Session,
    name: str,
    role: str = "readonly",
) -> tuple[ApiKey, str]:
    """Create a new API key. Returns (db_record, raw_key).

    The raw key is shown once and never stored.
    """
    if role not in ROLE_HIERARCHY:
        raise ValueError(f"Invalid role: {role}. Must be one of {list(ROLE_HIERARCHY)}")

    raw_key = secrets.token_urlsafe(32)
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()
    key_prefix = raw_key[:8]

    api_key = ApiKey(
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        role=role,
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    logger.info("Created API key '%s' (role=%s, prefix=%s)", name, role, key_prefix)
    return api_key, raw_key


def validate_key(db: Session, raw_key: str) -> Optional[ApiKey]:
    """Validate a raw API key. Returns the ApiKey record or None."""
    prefix = raw_key[:8]
    candidates = (
        db.query(ApiKey)
        .filter(ApiKey.key_prefix == prefix, ApiKey.is_active.is_(True))
        .all()
    )

    for candidate in candidates:
        if bcrypt.checkpw(raw_key.encode(), candidate.key_hash.encode()):
            # Update last_used_at
            candidate.last_used_at = datetime.utcnow()
            db.commit()
            return candidate

    return None


def has_permission(role: str, required_role: str) -> bool:
    """Check if a role meets the minimum required role level."""
    return ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY.get(required_role, 99)


def revoke_key(db: Session, key_id: int) -> bool:
    """Deactivate an API key."""
    key = db.query(ApiKey).get(key_id)
    if not key:
        return False
    key.is_active = False
    db.commit()
    logger.info("Revoked API key '%s' (id=%d)", key.name, key_id)
    return True
