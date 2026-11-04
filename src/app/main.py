from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import client
from app.routes.route import router

@asynccontextmanager
async def lifespan(app:FastAPI):
    await client.admin.command("ping")
    print("database connected")
    yield
    await client.close()

app = FastAPI(title="fillo", lifespan=lifespan)

app.include_router(router)

