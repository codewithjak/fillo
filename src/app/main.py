from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.config import settings
from app.db import client, db
from app.routes.route import router
from app.routes.status import router as status_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.admin.command("ping")
    print("database connected")

    await db.files.create_index([("source_id", 1), ("path", 1)], unique=True)
    await db.pages.create_index([("file_id", 1), ("page", 1)])
    await db.files.update_many({"status": "processing"}, {"$set": {"status": "pending"}})

    yield
    await client.close()


app = FastAPI(title="fillo", lifespan=lifespan)

app.include_router(router)
app.include_router(status_router)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.PORT, reload=True)