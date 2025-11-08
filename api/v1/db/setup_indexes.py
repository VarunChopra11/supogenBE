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


# async def setup_vector_index():
#     """Ensure vector search index exists for document chunks."""
#     db = DatabaseSession.get_db()
#     collection = db["embedded_documents"]  # replace with your actual collection name

#     index_name = "chunks_vector_index"

#     # Definition must be wrapped under `definition` for createSearchIndexes
#     index_def = {
#         "name": index_name,
#         "definition": {
#             "mappings": {
#                 "dynamic": True,
#                 "fields": {
#                     "embedding": {
#                         "type": "knnVector",
#                         "dimensions": 1536,
#                         "similarity": "cosine",
#                     },
#                     "server_id": {"type": "string"},
#                     "user_id": {"type": "string"},
#                     "created_at": {"type": "date"},
#                 },
#             }
#         }
#     }

#     # Best-effort: skip creation if index already exists (supported on MongoDB 7+/Atlas)
#     try:
#         existing = await db.command({
#             "listSearchIndexes": collection.name,
#             "name": index_name,
#         })
#         first_batch = existing.get("cursor", {}).get("firstBatch", [])
#         if any(ix.get("name") == index_name for ix in first_batch):
#             print("✅ Vector search index already exists on chunks.embedding")
#             return
#     except Exception:
#         # If command unsupported, proceed to attempt creation
#         pass

#     # Create or update the search index definition
#     await db.command({
#         "createSearchIndexes": collection.name,
#         "indexes": [index_def],
#     })

#     print("✅ Vector search index ensured on chunks.embedding (1536-d cosine)")
