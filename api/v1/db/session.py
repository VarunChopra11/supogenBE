from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional

class DatabaseSession:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorClient] = None

    @classmethod
    def get_db(cls) -> AsyncIOMotorClient:
        assert cls.db is not None, "Database not initialized!"
        if cls.client is None:
            raise RuntimeError("Database client is not connected.")
        return cls.db

    @classmethod
    async def connect(cls, uri: str, db_name: str):
        cls.client = AsyncIOMotorClient(
            uri,
            maxPoolSize=100,
            minPoolSize=10
        )
        cls.db = cls.client[db_name]
        print("Database connected")

    @classmethod
    async def close(cls):
        if cls.client:
            cls.client.close()
            