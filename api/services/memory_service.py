"""Memory service — create, search, and manage lab knowledge entries."""

import logging
from typing import Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from api.models.memory import MemoryEntry

logger = logging.getLogger(__name__)


def create_entry(
    db: Session,
    entry_type: str,
    title: str,
    content: str,
    tags: Optional[list[str]] = None,
    relevance: str = "medium",
    source_type: Optional[str] = None,
    source_id: Optional[int] = None,
) -> MemoryEntry:
    """Create a new memory entry."""
    entry = MemoryEntry(
        entry_type=entry_type,
        title=title,
        content=content,
        tags=tags,
        relevance=relevance,
        source_type=source_type,
        source_id=source_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info("Memory entry #%d created: [%s] %s", entry.id, entry_type, title)
    return entry


def search_keyword(
    db: Session,
    query: str,
    tags: Optional[list[str]] = None,
    entry_type: Optional[str] = None,
    limit: int = 20,
) -> list[MemoryEntry]:
    """Search memory entries by keyword (title + content) and optional filters."""
    q = db.query(MemoryEntry).filter(MemoryEntry.is_active.is_(True))

    if query:
        pattern = f"%{query}%"
        q = q.filter(
            or_(
                MemoryEntry.title.ilike(pattern),
                MemoryEntry.content.ilike(pattern),
            )
        )

    if entry_type:
        q = q.filter(MemoryEntry.entry_type == entry_type)

    if tags:
        # Filter entries that have any matching tag via ILIKE on JSON text
        tag_conditions = []
        for tag in tags:
            tag_conditions.append(
                text("CAST(tags AS TEXT) ILIKE :tag").bindparams(tag=f"%{tag}%")
            )
        q = q.filter(or_(*tag_conditions))

    return q.order_by(MemoryEntry.created_at.desc()).limit(limit).all()


def search_by_tags(
    db: Session,
    tags: list[str],
    limit: int = 20,
) -> list[MemoryEntry]:
    """Find entries that have any of the given tags."""
    q = db.query(MemoryEntry).filter(MemoryEntry.is_active.is_(True))
    # Use ILIKE on JSON-serialized tags column for cross-DB compatibility
    conditions = []
    for tag in tags:
        conditions.append(MemoryEntry.tags.cast(str).ilike(f"%{tag}%"))
    if conditions:
        q = q.filter(or_(*conditions))
    return q.order_by(MemoryEntry.created_at.desc()).limit(limit).all()


def auto_extract_from_round(db: Session, round_id: int) -> list[MemoryEntry]:
    """Extract memory entries from an ExplorationRound's results.

    Creates experiment_summary entries for each high-scoring result.
    """
    from api.models.ai_lab import ExplorationRound

    round_obj = db.query(ExplorationRound).get(round_id)
    if not round_obj:
        logger.warning("ExplorationRound #%d not found", round_id)
        return []

    entries = []
    title = round_obj.title or f"Round #{round_id}"

    # Create a summary entry for the round itself
    content_parts = [f"Exploration round: {title}"]
    if round_obj.goal:
        content_parts.append(f"Goal: {round_obj.goal}")
    if round_obj.findings:
        content_parts.append(f"Findings: {round_obj.findings}")

    entry = create_entry(
        db,
        entry_type="experiment_summary",
        title=f"R{round_id}: {title}",
        content="\n".join(content_parts),
        tags=["exploration", f"round-{round_id}"],
        relevance="high",
        source_type="exploration_round",
        source_id=round_id,
    )
    entries.append(entry)

    logger.info("Auto-extracted %d memory entries from round #%d", len(entries), round_id)
    return entries
