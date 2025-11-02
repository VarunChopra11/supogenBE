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


async def setup_vector_index():
    """Ensure vector search index exists for document chunks."""
    db = DatabaseSession.get_db()
    collection = db["chunks"]  # replace with your actual collection name

    index_def = {
        "name": "chunks_vector_index",
        "mappings": {
            "dynamic": True,
            "fields": {
                "embedding": {
                    "type": "vectorSearch",
                    "dimensions": 1536,
                    "similarity": "cosine"
                },
                "server_id": {"type": "string"},
                "user_id": {"type": "string"},
                "created_at": {"type": "date"}
            }
        }
    }

    # Motor (async driver) currently doesn’t have create_search_index helper,
    # so we call the raw command directly:
    await db.command({
        "createSearchIndexes": collection.name,
        "indexes": [index_def]
    })

    print("✅ Vector search index ensured on chunks.embedding (1536-d cosine)")
