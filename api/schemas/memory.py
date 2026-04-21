"""Pydantic schemas for Lab Memory API."""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel


class MemoryEntryCreate(BaseModel):
    entry_type: str = "insight"
    title: str
    content: str
    tags: Optional[list[str]] = None
    relevance: str = "medium"
    source_type: Optional[str] = None
    source_id: Optional[int] = None


class MemoryEntryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    relevance: Optional[str] = None
    is_active: Optional[bool] = None
    superseded_by: Optional[int] = None


class MemoryEntryResponse(BaseModel):
    id: int
    entry_type: str
    title: str
    content: str
    tags: Optional[list] = None
    relevance: str
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    pinecone_synced: bool = False
    file_synced: bool = False
    is_active: bool = True
    superseded_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class MemorySearchResult(BaseModel):
    entries: list[MemoryEntryResponse]
    total: int
