from fastapi import APIRouter, status, BackgroundTasks, HTTPException
from app.schema.index import DocOutput, DocInput
from app.ingestion.scanner import scan_folder
from app.ingestion.worker import process_source

router = APIRouter(prefix="/api/v1/{path-url}", tags=["fillo"]);
@router.post("", response_model=DocOutput, status_code=status.HTTP_202_ACCEPTED)
async def upload_docs(body: DocInput, background_tasks: BackgroundTasks) -> DocOutput:
    root = Path(body.url).resolve()

    if not root.is_dir():
        raise HTTPException(400, "Folder not found")
    if not any(root.is_relative_to(Path(r).resolve()) for r in settings.allowed_roots):
        raise HTTPException(403, "Folder is outside the allowed roots")

    files = await asyncio.to_thread(scan_folder, root)   # keep the event loop free

    db = get_db()
    now = datetime.now(timezone.utc)
    source_id, job_id = uuid.uuid4().hex, uuid.uuid4().hex

    await db.sources.insert_one({"_id": source_id, "path": str(root),
                                 "total": len(files), "created_at": now})
    if files:
        await db.files.bulk_write([
            UpdateOne(
                {"source_id": source_id, "path": f["path"]},
                {"$set": {**f, "source_id": source_id}, "$setOnInsert": {"created_at": now}},
                upsert=True,
            ) for f in files
        ])
    await db.jobs.insert_one({"_id": job_id, "source_id": source_id,
                              "status": "running", "created_at": now})

    background_tasks.add_task(process_source, source_id, job_id)
    return DocOutput(source_id=source_id, job_id=job_id, total=len(files))

