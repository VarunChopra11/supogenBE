from .session import DatabaseSession

async def setup_ttl_indexes():
    """Ensure TTL indexes exist in MongoDB."""
    db = DatabaseSession.get_db()

    # TTL index for invalid_tokens collection
    await db["invalid_tokens"].create_index(
        "added_at",
        expireAfterSeconds=360,  # 6 minutes
        name="expire_invalid_tokens_after_6m"
    )

    print("✅ TTL index ensured on invalid_tokens.added_at (6 minutes)")
