from fastapi import APIRouter, HTTPException

from app.db import db

router = APIRouter(prefix="/api/v1", tags=["fillo"])


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = await db.jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")
    cursor = await db.files.aggregate([
        {"$match": {"source_id": job["source_id"]}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ])
    files = {row["_id"]: row["n"] for row in await cursor.to_list(None)}
    return {**job, "files": files}


@router.get("/sources/{source_id}/files")
async def list_files(source_id: str):
    cursor = db.files.find(
        {"source_id": source_id},
        {"_id": 0, "name": 1, "status": 1, "pages": 1, "chars": 1, "error": 1},
    )
    return await cursor.to_list(None)


@router.get("/sources/{source_id}/pages")
async def get_pages(source_id: str, name: str):
    """OCR text for one file, e.g. ?name=sara CNIC.jpeg"""
    file = await db.files.find_one({"source_id": source_id, "name": name})
    if not file:
        raise HTTPException(404, "File not found")
    cursor = db.pages.find(
        {"file_id": file["_id"]},
        {"_id": 0, "page": 1, "method": 1, "confidence": 1, "text": 1},
    ).sort("page", 1)
    return await cursor.to_list(None)

@router.get("/sources/{source_id}/files")
async def list_files(source_id: str, status: str | None = None):
    query = {"source_id": source_id}
    if status:
        query["status"] = status
    cursor = db.files.find(
        query,
        {"_id": 0, "name": 1, "status": 1, "pages": 1, "chars": 1, "error": 1},
    )
    return await cursor.to_list(None)
