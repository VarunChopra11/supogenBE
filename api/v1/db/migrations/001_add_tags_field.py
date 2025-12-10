from api.v1.db.session import DatabaseSession
from api.v1.config import db_config
import asyncio

async def run_migration():

    await DatabaseSession.connect(
        uri=db_config.MONGO_URI,
        db_name=db_config.MONGO_DB_NAME
    )

    db = DatabaseSession.get_db()

    result = await db["discord_servers"].update_many(
        {"server_tags": {"$exists": False}},
        {"$set": {"server_tags": None}}
    )

    print("Modified:", result.modified_count)
    print("Migration complete 🚀")


asyncio.run(run_migration())