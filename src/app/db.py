from pymongo import AsyncMongoClient
from app.config import settings


client = AsyncMongoClient(settings.MONGO_URI)
db = client[settings.db]