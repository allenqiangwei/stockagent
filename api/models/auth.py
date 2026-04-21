"""Auth models — API keys and audit log."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), comment="Device/client name")
    key_hash: Mapped[str] = mapped_column(String(200), comment="bcrypt hash")
    key_prefix: Mapped[str] = mapped_column(
        String(8), index=True, comment="First 8 chars for quick lookup"
    )
    role: Mapped[str] = mapped_column(
        String(20), default="readonly", comment="admin|operator|readonly"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
    api_key_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    api_key_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(500))
    status_code: Mapped[int] = mapped_column(Integer)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    request_body_preview: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="First 500 chars of request body"
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
