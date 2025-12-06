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

    async def get_discord_chat_by_thread(
        self,
        thread_id: str,
        user_id: str,
    ) -> Optional[DiscordChat]:
        """Get a Discord chat by thread_id, ensuring it belongs to the user."""
        db = DatabaseSession.get_db()
        doc = await db[self.discord_collection].find_one(
            {"thread_id": str(thread_id), "user_id": user_id}
        )
        if doc:
            return DiscordChat(**doc)
        return None

    async def get_discord_chat_by_id(
        self,
        chat_id: str,
        user_id: str,
    ) -> Optional[DiscordChat]:
        """Get a Discord chat by chat_id, ensuring it belongs to the user."""
        db = DatabaseSession.get_db()
        doc = await db[self.discord_collection].find_one(
            {"chat_id": chat_id, "user_id": user_id}
        )
        if doc:
            return DiscordChat(**doc)
        return None

    async def mark_discord_chat_resolved(
        self,
        thread_id: str,
        is_resolved: bool,
    ) -> bool:
        """
        Mark a Discord chat as resolved or pending based on thread_id.
        Updates resolution_time based on the resolution status.
        
        Args:
            thread_id: The Discord thread ID
            is_resolved: True to mark as resolved, False to mark as pending
            
        Returns:
            bool: True if update was successful, False otherwise
        """
        db = DatabaseSession.get_db()
        
        # First, fetch the chat to get created_at for resolution_time calculation
        chat_doc = await db[self.discord_collection].find_one(
            {"thread_id": str(thread_id)}
        )
        
        if not chat_doc:
            return False
        
        current_time = datetime.now(timezone.utc)
        update_fields = {
            "is_resolved": is_resolved,
            "updated_at": current_time,
        }
        
        # Calculate resolution_time based on is_resolved status
        if is_resolved:
            # When marking as resolved, calculate time from created_at
            created_at = chat_doc.get("created_at")
            if created_at:
                # Ensure created_at is timezone-aware
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                resolution_time = (current_time - created_at).total_seconds()
                update_fields["resolution_time"] = resolution_time
            else:
                update_fields["resolution_time"] = None
        else:
            # When marking as pending, set resolution_time to None
            update_fields["resolution_time"] = None
        
        result = await db[self.discord_collection].update_one(
            {"thread_id": str(thread_id)},
            {"$set": update_fields},
        )
        return result.modified_count > 0

    async def auto_resolve_old_chats(self, days_threshold: int = 4) -> int:
        """
        Auto-resolve Discord chats that haven't been updated in specified days.
        Calculates resolution_time for each auto-resolved chat.
        
        Args:
            days_threshold: Number of days after which to auto-resolve (default: 4)
            
        Returns:
            int: Number of chats auto-resolved
        """
        from datetime import timedelta
        
        db = DatabaseSession.get_db()
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_threshold)
        current_time = datetime.now(timezone.utc)
        
        # Find all chats that need to be auto-resolved
        chats_to_resolve = await db[self.discord_collection].find(
            {
                "is_resolved": False,
                "updated_at": {"$lte": cutoff_time}
            }
        ).to_list(length=None)
        
        # Update each chat individually to calculate resolution_time
        updated_count = 0
        for chat in chats_to_resolve:
            created_at = chat.get("created_at")
            resolution_time = None
            
            if created_at:
                # Ensure created_at is timezone-aware
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                resolution_time = (current_time - created_at).total_seconds()
            
            await db[self.discord_collection].update_one(
                {"_id": chat["_id"]},
                {
                    "$set": {
                        "is_resolved": True,
                        "resolution_time": resolution_time,
                        "updated_at": current_time,
                    }
                },
            )
            updated_count += 1
        
        return updated_count


chat_service = ChatService()
