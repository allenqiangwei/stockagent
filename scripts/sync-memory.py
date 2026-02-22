#!/usr/bin/env python3
"""Sync memory notes to Pinecone index.

Usage:
    python scripts/sync-memory.py --full     # full rebuild
    python scripts/sync-memory.py            # incremental (new/changed only)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

MEMORY_DIR = Path(os.environ.get(
    "MEMORY_DIR",
    os.path.expanduser("~/.claude/projects/-Users-allenqiang-stockagent/memory")
))
INDEX_FILE = MEMORY_DIR / "meta" / "index.json"
PINECONE_INDEX = "stockagent-memory"
PINECONE_NAMESPACE = "default"


def parse_note(filepath: Path) -> dict | None:
    """Parse a memory note file, extracting frontmatter and body."""
    text = filepath.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.+?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        return None
    front = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    if not front or "id" not in front:
        return None
    rel_path = str(filepath.relative_to(MEMORY_DIR))
    tags = front.get("tags", [])
    return {
        "_id": front["id"],
        "text": body,
        "type": front.get("type", "").split("/")[0],
        "subtype": front.get("type", "").split("/")[-1],
        "tags": ",".join(tags) if isinstance(tags, list) else str(tags),
        "relevance": front.get("relevance", "medium"),
        "created": str(front.get("created", "")),
        "file_path": rel_path,
    }


def collect_notes() -> list[dict]:
    """Collect all memory notes from the memory directory."""
    notes = []
    for md in MEMORY_DIR.rglob("*.md"):
        if md.name == "MEMORY.md":
            continue
        note = parse_note(md)
        if note:
            notes.append(note)
    return notes


def update_index(notes: list[dict]):
    """Update meta/index.json from collected notes."""
    entries = []
    for n in notes:
        entries.append({
            "id": n["_id"],
            "file": n["file_path"],
            "type": n["type"],
            "tags": n["tags"].split(",") if n["tags"] else [],
            "relevance": n["relevance"],
        })
    index_data = {
        "version": 1,
        "updated": __import__("datetime").date.today().isoformat(),
        "notes": sorted(entries, key=lambda x: x["id"]),
    }
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps(index_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {INDEX_FILE} with {len(entries)} notes")


def sync_pinecone(notes: list[dict]):
    """Upsert notes to Pinecone. Requires PINECONE_API_KEY env var."""
    api_key = os.environ.get("PINECONE_API_KEY")
    if not api_key:
        print("PINECONE_API_KEY not set, skipping Pinecone sync")
        print("Set it to enable semantic search: export PINECONE_API_KEY=...")
        return

    try:
        from pinecone import Pinecone
    except ImportError:
        print("pinecone package not installed. Run: pip install pinecone")
        return

    pc = Pinecone(api_key=api_key)
    idx = pc.Index(PINECONE_INDEX)

    # Upsert in batches of 20
    batch_size = 20
    for i in range(0, len(notes), batch_size):
        batch = notes[i:i + batch_size]
        records = []
        for n in batch:
            records.append({
                "_id": n["_id"],
                "text": n["text"][:8000],  # truncate for embedding
                "type": n["type"],
                "subtype": n["subtype"],
                "tags": n["tags"],
                "relevance": n["relevance"],
                "created": n["created"],
                "file_path": n["file_path"],
            })
        idx.upsert_records(PINECONE_NAMESPACE, records)
        print(f"Upserted {len(records)} records (batch {i // batch_size + 1})")

    print(f"Pinecone sync complete: {len(notes)} records in {PINECONE_INDEX}")


def main():
    parser = argparse.ArgumentParser(description="Sync memory notes to Pinecone")
    parser.add_argument("--full", action="store_true", help="Full rebuild (default: incremental)")
    args = parser.parse_args()

    notes = collect_notes()
    print(f"Found {len(notes)} memory notes")

    if not notes:
        print("No notes found. Check MEMORY_DIR path.")
        sys.exit(1)

    update_index(notes)
    sync_pinecone(notes)


if __name__ == "__main__":
    main()
