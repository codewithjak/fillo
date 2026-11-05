import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pymongo import UpdateOne

from app.config import settings
from app.db import db
from app.ingestion.scanner import scan_folder


class SourcePathError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def resolve_allowed_source_root(raw_path: str) -> Path:
    path = Path(raw_path.strip()).expanduser()
    if not path.is_absolute():
        raise SourcePathError(400, "path must be an absolute folder path")

    try:
        configured_roots = [root.expanduser().resolve() for root in settings.allowed_source_roots]
        root = path.resolve()
    except (OSError, RuntimeError) as e:
        raise SourcePathError(400, "Invalid folder path") from e

    if not configured_roots:
        raise SourcePathError(503, "No allowed source folders are configured")

    existing_roots = [allowed for allowed in configured_roots if allowed.is_dir()]
    if not existing_roots:
        raise SourcePathError(503, "Configured source folders are unavailable")
    if not any(root == allowed or root.is_relative_to(allowed) for allowed in existing_roots):
        raise SourcePathError(403, "Folder is outside the allowed source folders")
    if not root.is_dir():
        raise SourcePathError(400, "Folder not found")
    return root


async def register_source_root(
    root: Path,
    schedule_job: Callable[[str, str], None],
    *,
    metadata: dict | None = None,
) -> dict:
    """Create source/file/job records and schedule the existing ingestion worker."""
    files = await asyncio.to_thread(scan_folder, root)
    if not files:
        raise SourcePathError(400, "No files found in this folder")

    now = datetime.now(timezone.utc)
    source_id, job_id = uuid.uuid4().hex, uuid.uuid4().hex
    source_record = {
        "_id": source_id,
        "path": str(root),
        "total": len(files),
        "created_at": now,
        **(metadata or {}),
    }
    await db.sources.insert_one(source_record)
    await db.files.bulk_write([
        UpdateOne(
            {"source_id": source_id, "path": file["path"]},
            {
                "$set": {**file, "source_id": source_id},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        for file in files
    ])
    await db.jobs.insert_one({
        "_id": job_id,
        "source_id": source_id,
        "status": "pending",
        "created_at": now,
    })
    schedule_job(source_id, job_id)
    return {"source_id": source_id, "job_id": job_id, "total": len(files), "status": "pending"}
