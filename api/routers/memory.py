"""Memory router — CRUD and search for lab knowledge entries."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.deps import require_role
from api.models.base import get_db
from api.models.memory import MemoryEntry
from api.schemas.memory import (
    MemoryEntryCreate,
    MemoryEntryUpdate,
    MemoryEntryResponse,
    MemorySearchResult,
)
from api.services.memory_service import create_entry, search_keyword, auto_extract_from_round

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _to_response(e: MemoryEntry) -> MemoryEntryResponse:
    return MemoryEntryResponse(
        id=e.id,
        entry_type=e.entry_type,
        title=e.title,
        content=e.content,
        tags=e.tags,
        relevance=e.relevance,
        source_type=e.source_type,
        source_id=e.source_id,
        pinecone_synced=e.pinecone_synced,
        file_synced=e.file_synced,
        is_active=e.is_active,
        superseded_by=e.superseded_by,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


@router.get("/search", response_model=MemorySearchResult)
def search_memory(
    q: str = Query("", description="Keyword search"),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    entry_type: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Search memory entries by keyword and/or tags."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    entries = search_keyword(db, q, tags=tag_list, entry_type=entry_type, limit=limit)
    return MemorySearchResult(
        entries=[_to_response(e) for e in entries],
        total=len(entries),
    )


@router.get("/entries", response_model=list[MemoryEntryResponse])
def list_entries(
    entry_type: Optional[str] = Query(None),
    relevance: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List memory entries with optional filters."""
    q = db.query(MemoryEntry).filter(MemoryEntry.is_active.is_(True))
    if entry_type:
        q = q.filter(MemoryEntry.entry_type == entry_type)
    if relevance:
        q = q.filter(MemoryEntry.relevance == relevance)
    entries = q.order_by(MemoryEntry.created_at.desc()).limit(limit).all()
    return [_to_response(e) for e in entries]


@router.get("/entries/{entry_id}", response_model=MemoryEntryResponse)
def get_entry(entry_id: int, db: Session = Depends(get_db)):
    """Get a single memory entry."""
    entry = db.query(MemoryEntry).get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return _to_response(entry)


@router.post("/entries", response_model=MemoryEntryResponse)
def create_memory_entry(body: MemoryEntryCreate, db: Session = Depends(get_db)):
    """Create a new memory entry."""
    entry = create_entry(
        db,
        entry_type=body.entry_type,
        title=body.title,
        content=body.content,
        tags=body.tags,
        relevance=body.relevance,
        source_type=body.source_type,
        source_id=body.source_id,
    )
    return _to_response(entry)


@router.put("/entries/{entry_id}", response_model=MemoryEntryResponse)
def update_entry(
    entry_id: int,
    body: MemoryEntryUpdate,
    db: Session = Depends(get_db),
):
    """Update a memory entry."""
    entry = db.query(MemoryEntry).get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Memory entry not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return _to_response(entry)


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    """Soft-delete a memory entry (set is_active=False)."""
    entry = db.query(MemoryEntry).get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    entry.is_active = False
    db.commit()
    return {"status": "deleted"}


@router.post(
    "/auto-extract/{round_id}",
    response_model=list[MemoryEntryResponse],
)
def auto_extract(round_id: int, db: Session = Depends(get_db)):
    """Auto-extract memory entries from an ExplorationRound."""
    entries = auto_extract_from_round(db, round_id)
    if not entries:
        raise HTTPException(status_code=404, detail="Round not found or no entries extracted")
    return [_to_response(e) for e in entries]
