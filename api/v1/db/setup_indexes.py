from .session import DatabaseSession

async def setup_ttl_indexes():
    """Ensure TTL indexes exist in MongoDB."""
    db = DatabaseSession.get_db()

    await db["invalid_tokens"].create_index(
        "added_at",
        expireAfterSeconds=360,
        name="expire_invalid_tokens_after_6m"
    )

    print("✅ TTL index ensured on invalid_tokens.added_at (6 minutes)")

    # Chats: common lookup pattern and sorting
    await db["playground_chats"].create_index(
        [("user_id", 1), ("server_id", 1), ("updated_at", -1)],
        name="playground_user_server_updated_idx",
    )
    await db["playground_chats"].create_index("chat_id", unique=True, name="playground_chat_id_uidx")

    await db["discord_chats"].create_index(
        [("user_id", 1), ("server_id", 1), ("updated_at", -1)],
        name="discord_user_server_updated_idx",
    )
    await db["discord_chats"].create_index("chat_id", unique=True, name="discord_chat_id_uidx")
    
    # Index for thread_id lookup (Discord chat history)
    await db["discord_chats"].create_index(
        [("thread_id", 1), ("user_id", 1)],
        name="discord_thread_user_idx",
    )
    
    # Index for resolution status queries
    await db["discord_chats"].create_index(
        [("is_resolved", 1), ("updated_at", 1)],
        name="discord_resolution_updated_idx",
    )
    
    # Compound index for efficient auto-resolve queries
    await db["discord_chats"].create_index(
        [("is_resolved", 1), ("updated_at", 1), ("user_id", 1)],
        name="discord_auto_resolve_idx",
    )

    print("✅ All indexes created successfully")


async def setup_discord_context_index():
    db = DatabaseSession.get_db()
    collection_name = "discord_context_chunks"
    index_name = "discord_context_vector_index"

    # 1. Ensure collection exists (required for Vector Search index creation)
    existing_collections = await db.list_collection_names()
    if collection_name not in existing_collections:
        await db.create_collection(collection_name)
        print(f"✅ Collection '{collection_name}' created.")

    # 2. Check if index exists to avoid re-creation errors
    try:
        cursor = db[collection_name].list_search_indexes(index_name)
        async for index in cursor:
            if index.get("name") == index_name:
                print(f"✅ Vector index '{index_name}' already exists.")
                return
    except Exception as e:
        # If the command fails or index doesn't exist, proceed to create
        pass

    # 3. Define the Atlas Vector Search Index
    index_model = {
        "name": index_name,
        "type": "vectorSearch", 
        "definition": {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": 1536,
                    "similarity": "cosine"
                },
                {
                    "type": "filter",
                    "path": "server_id"
                }
            ]
        }
    }

    # 4. Create the index
    print(f"⏳ Creating vector index '{index_name}'...")
    try:
        await db.command({
            "createSearchIndexes": collection_name,
            "indexes": [index_model]
        })
        print(f"✅ Vector search index '{index_name}' creation initiated.")
    except Exception as e:
        print(f"❌ Failed to create vector index: {e}")


async def setup_vector_index():
    """Ensure vector search index exists for document chunks."""
    db = DatabaseSession.get_db()
    collection_name = "embedded_documents"
    index_name = "chunks_vector_index"

    # 1. Ensure collection exists
    existing_collections = await db.list_collection_names()
    if collection_name not in existing_collections:
        await db.create_collection(collection_name)
        print(f"✅ Collection '{collection_name}' created.")

    # 2. Check if index exists
    try:
        cursor = db[collection_name].list_search_indexes(index_name)
        async for index in cursor:
            if index.get("name") == index_name:
                print(f"✅ Vector index '{index_name}' already exists on {collection_name}.")
                return
    except Exception:
        pass

    # 3. Define the Atlas Vector Search Index
    index_model = {
        "name": index_name,
        "type": "vectorSearch",
        "definition": {
            "fields": [
                {
                    "numDimensions": 1536,
                    "path": "embedding",
                    "similarity": "cosine",
                    "type": "vector"
                },
                {
                    "path": "user_id",
                    "type": "filter"
                },
                {
                    "path": "server_id",
                    "type": "filter"
                }
            ]
        }
    }

    # 4. Create the index
    print(f"⏳ Creating vector index '{index_name}'...")
    try:
        await db.command({
            "createSearchIndexes": collection_name,
            "indexes": [index_model]
        })
        print(f"✅ Vector search index '{index_name}' creation initiated.")
    except Exception as e:
        print(f"❌ Failed to create vector index '{index_name}': {e}")