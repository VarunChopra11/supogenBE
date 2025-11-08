from __future__ import annotations

from typing import List, Optional
from datetime import datetime, timezone
import uuid

from api.v1.db.session import DatabaseSession
from api.v1.schemas.chats import PlaygroundChat, DiscordChat, ChatMessage


class ChatService:
    playground_collection = "playground_chats"
    discord_collection = "discord_chats"

    async def create_playground_chat(
        self,
        user_id: str,
        server_id: str,
        first_message: Optional[ChatMessage] = None,
    ) -> str:
        db = DatabaseSession.get_db()
        chat_id = str(uuid.uuid4())
        doc = PlaygroundChat(
            chat_id=chat_id,
            user_id=user_id,
            server_id=server_id,
            messages=[first_message] if first_message else [],
        ).model_dump()
        await db[self.playground_collection].insert_one(doc)
        return chat_id

    async def append_playground_message(
        self,
        chat_id: str,
        message: ChatMessage,
    ) -> None:
        db = DatabaseSession.get_db()
        await db[self.playground_collection].update_one(
            {"chat_id": chat_id},
            {
                "$push": {"messages": message.model_dump()},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    async def get_playground_chat_history(
        self,
        user_id: str,
        server_id: str,
        limit: int = 20,
    ) -> List[PlaygroundChat]:
        db = DatabaseSession.get_db()
        cursor = (
            db[self.playground_collection]
            .find({"user_id": user_id, "server_id": server_id})
            .sort("updated_at", -1)
            .limit(limit)
        )
        chats: List[PlaygroundChat] = []
        async for doc in cursor:
            chats.append(PlaygroundChat(**doc))
        return chats

    async def get_playground_chat_by_id(
        self,
        chat_id: str,
        user_id: str,
    ) -> Optional[PlaygroundChat]:
        """Get a specific playground chat by chat_id, ensuring it belongs to the user."""
        db = DatabaseSession.get_db()
        doc = await db[self.playground_collection].find_one(
            {"chat_id": chat_id, "user_id": user_id}
        )
        if doc:
            return PlaygroundChat(**doc)
        return None

    # Discord helpers for completeness
    async def create_discord_chat(
        self,
        user_id: str,
        server_id: str,
        channel_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        first_message: Optional[ChatMessage] = None,
    ) -> str:
        db = DatabaseSession.get_db()
        chat_id = str(uuid.uuid4())
        doc = DiscordChat(
            chat_id=chat_id,
            user_id=user_id,
            server_id=server_id,
            channel_id=channel_id,
            thread_id=thread_id,
            messages=[first_message] if first_message else [],
        ).model_dump()
        await db[self.discord_collection].insert_one(doc)
        return chat_id

    async def append_discord_message(self, chat_id: str, message: ChatMessage) -> None:
        db = DatabaseSession.get_db()
        await db[self.discord_collection].update_one(
            {"chat_id": chat_id},
            {
                "$push": {"messages": message.model_dump()},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )


chat_service = ChatService()
