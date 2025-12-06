from .session import DatabaseSession
from api.v1.config import db_config
from .setup_indexes import setup_ttl_indexes, setup_discord_context_index, setup_vector_index

async def init_db():
    await DatabaseSession.connect(
        uri=db_config.MONGO_URI,
        db_name=db_config.MONGO_DB_NAME
    )

    # Ensure indexes only once during startup
    await setup_ttl_indexes()
    await setup_discord_context_index()
    await setup_vector_index()

async def close_db():
    await DatabaseSession.close()
    