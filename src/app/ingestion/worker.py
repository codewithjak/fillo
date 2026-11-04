from datetime import datetime, timezone
from pathlib import Path
from pymongo import ReturnDocument
from app.db import get_db

async def process_source(source_id: str, job_id: str) -> None:
    db = get_db()
    source = await db.sources.find_one({"_id": source_id})
    root = Path(source["path"])

    while True:
        doc = await db.files.find_one_and_update(      # atomically claim the next file
            {"source_id": source_id, "status": "pending"},
            {"$set": {"status": "processing"}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            break
        try:
            path = Path(doc["path"])
            if not path.is_file() or not path.resolve().is_relative_to(root):
                raise FileNotFoundError(doc["path"])
            # read → classify → extract → save facts   (next step)
            await db.files.update_one({"_id": doc["_id"]}, {"$set": {
                "status": "done", "processed_at": datetime.now(timezone.utc)}})
        except Exception as e:
            await db.files.update_one({"_id": doc["_id"]},
                                      {"$set": {"status": "failed", "error": str(e)}})

    await db.jobs.update_one({"_id": job_id}, {"$set": {"status": "done"}})