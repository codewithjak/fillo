import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo import UpdateOne

from app.config import settings
from app.db import db
from app.ingestion.scanner import scan_folder
from app.schema.index import DocOutput, SourceInput
from app.security import require_api_key

router = APIRouter(
    prefix="/api/v1/sources",
    tags=["fillo"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=DocOutput, status_code=status.HTTP_202_ACCEPTED)
async def create_source(body: SourceInput, request: Request) -> DocOutput:
    try:
        configured_roots = [root.expanduser().resolve() for root in settings.allowed_source_roots]
        root = Path(body.path).resolve()
    except (OSError, RuntimeError) as e:
        raise HTTPException(400, "Invalid folder path") from e

    if not configured_roots:
        raise HTTPException(503, "No allowed source folders are configured")

    existing_roots = [path for path in configured_roots if path.is_dir()]
    if not existing_roots:
        raise HTTPException(503, "Configured source folders are unavailable")
    if not any(root == allowed or root.is_relative_to(allowed) for allowed in existing_roots):
        raise HTTPException(403, "Folder is outside the allowed source folders")

    if not root.is_dir():
        raise HTTPException(400, "Folder not found")

    files = await asyncio.to_thread(scan_folder, root)   # keep the event loop free
    if not files:
        raise HTTPException(400, "No files found in this folder")

    now = datetime.now(timezone.utc)
    source_id, job_id = uuid.uuid4().hex, uuid.uuid4().hex

    await db.sources.insert_one({"_id": source_id, "path": str(root),
                                 "total": len(files), "created_at": now})
    await db.files.bulk_write([
        UpdateOne(
            {"source_id": source_id, "path": f["path"]},
            {"$set": {**f, "source_id": source_id}, "$setOnInsert": {"created_at": now}},
            upsert=True,
        ) for f in files
    ])
    await db.jobs.insert_one({"_id": job_id, "source_id": source_id,
                              "status": "pending", "created_at": now})

    request.app.state.schedule_job(source_id, job_id)
    return DocOutput(source_id=source_id, job_id=job_id, total=len(files))
