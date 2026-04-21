"""Memory model — structured lab knowledge entries."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, Text, JSON, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_type: Mapped[str] = mapped_column(
        String(30), index=True,
        comment="insight|issue|decision|hypothesis|experiment_summary",
    )
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    relevance: Mapped[str] = mapped_column(
        String(20), default="medium",
        comment="critical|high|medium|low",
    )
    source_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="experiment|exploration_round|trade_review|manual",
    )
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pinecone_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    file_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    superseded_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )
