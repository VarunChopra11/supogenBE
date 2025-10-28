from .session import DatabaseSession
from api.v1.config import db_config

async def init_db():
    await DatabaseSession.connect(
        uri=db_config.MONGO_URI,
        db_name=db_config.MONGO_DB_NAME
    )

async def close_db():
    await DatabaseSession.close()
    