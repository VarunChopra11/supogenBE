from .session import DatabaseSession
from api.v1.config import db_config
from .setup_indexes import setup_ttl_indexes

async def init_db():
    await DatabaseSession.connect(
        uri=db_config.MONGO_URI,
        db_name=db_config.MONGO_DB_NAME
    )

    # Ensure indexes only once during startup
    await setup_ttl_indexes()
    # await setup_vector_index()   # add this line

async def close_db():
    await DatabaseSession.close()
    