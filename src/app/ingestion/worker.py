from datetime import datetime, timezone
from pathlib import Path
from pymongo import ReturnDocument
from app.db import db
from app.ingestion.readers import read_document


async def process_source(source_id: str, job_id: str) -> None:
    try:
        source = await db.sources.find_one({"_id": source_id})
        root = Path(source["path"])

        while True:
            doc = await db.files.find_one_and_update(
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

                pages = await read_document(path)              # text layer / OCR / docx / txt
                chars = sum(len(p.text) for p in pages)
                if chars == 0:
                    raise ValueError("No text could be extracted")

                await db.pages.delete_many({"file_id": doc["_id"]})   # safe on re-runs
                await db.pages.insert_many([{
                    "_id": f"{doc['_id']}:{p.page}",
                    "file_id": doc["_id"],
                    "source_id": source_id,
                    "page": p.page,
                    "text": p.text,
                    "method": p.method,
                    "confidence": p.confidence,
                } for p in pages])

                await db.files.update_one({"_id": doc["_id"]}, {
                    "$set": {"status": "done", "pages": len(pages), "chars": chars,
                             "processed_at": datetime.now(timezone.utc)},
                    "$unset": {"error": ""},
                })
            except Exception as e:
                await db.files.update_one({"_id": doc["_id"]},
                                          {"$set": {"status": "failed", "error": str(e)}})

        counts = {s: await db.files.count_documents({"source_id": source_id, "status": s})
                  for s in ("done", "failed", "skipped")}
        await db.jobs.update_one({"_id": job_id}, {"$set": {"status": "done", **counts}})

    except Exception as e:
        await db.jobs.update_one({"_id": job_id},
                                 {"$set": {"status": "failed", "error": str(e)}})
        raise