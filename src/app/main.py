import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI

from app.config import settings
from app.db import client, db
from app.ingestion.worker import process_source
from app.routes.agent import router as agent_router
from app.routes.route import router
from app.routes.status import router as status_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.admin.command("ping")

    await db.files.create_index([("source_id", 1), ("path", 1)], unique=True)
    await db.pages.create_index([("file_id", 1), ("page", 1)])
    await db.files.update_many({"status": "processing"}, {"$set": {"status": "pending"}})
    await db.jobs.update_many(
        {"status": {"$in": ["running", "incomplete"]}},
        {"$set": {"status": "pending", "recovered_at": datetime.now(timezone.utc)}},
    )

    tasks: dict[str, asyncio.Task] = {}

    def schedule_job(source_id: str, job_id: str) -> None:
        current = tasks.get(job_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(process_source(source_id, job_id))
        tasks[job_id] = task

        def finished(completed: asyncio.Task, *, key: str = job_id) -> None:
            if tasks.get(key) is completed:
                tasks.pop(key, None)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                logger.error("Document job %s stopped unexpectedly: %s", key, error,
                             exc_info=(type(error), error, error.__traceback__))

        task.add_done_callback(finished)

    app.state.schedule_job = schedule_job

    pending_jobs = await db.jobs.find(
        {"status": "pending"}, {"_id": 1, "source_id": 1}
    ).to_list(None)
    for job in pending_jobs:
        schedule_job(job["source_id"], job["_id"])

    yield

    running_tasks = list(tasks.values())
    for task in running_tasks:
        task.cancel()
    if running_tasks:
        await asyncio.gather(*running_tasks, return_exceptions=True)
    await client.close()


app = FastAPI(title="fillo", lifespan=lifespan)

app.include_router(router)
app.include_router(status_router)
app.include_router(agent_router)


def main() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.PORT)


if __name__ == "__main__":
    main()
