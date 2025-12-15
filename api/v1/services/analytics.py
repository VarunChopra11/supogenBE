from __future__ import annotations

from typing import List

from api.v1.db.session import DatabaseSession
from api.v1.schemas.chats import DiscordChat


class AnalyticsService:
    discord_collection = "discord_chats"

    async def get_discord_analytics(self, user_id: str) -> dict:
        """
        Get analytics for Discord chats for a specific user.
        
        Returns:
            dict: Analytics data including total tickets, resolution time, and first contact resolution
        """
        db = DatabaseSession.get_db()
        
        # Get all discord chats for the user
        all_chats = await db[self.discord_collection].find(
            {"user_id": user_id}
        ).to_list(length=None)
        
        total_tickets = len(all_chats)
        total_resolved_tickets = sum(1 for chat in all_chats if chat.get("is_resolved", False))
        
        # Calculate average resolution time (only for resolved chats with resolution_time)
        resolved_with_time = [
            chat.get("resolution_time") 
            for chat in all_chats 
            if chat.get("is_resolved") and chat.get("resolution_time") is not None
        ]
        
        avg_resolution_time = None
        if resolved_with_time:
            avg_resolution_seconds = sum(resolved_with_time) / len(resolved_with_time)
            avg_resolution_time = avg_resolution_seconds / 3600  # Convert to hours
        
        # Calculate first contact resolution
        # First contact resolution: exactly 3 messages (system, user, assistant)
        # or 2 messages (user, assistant) if no system message
        first_contact_resolved = 0
        for chat in all_chats:
            messages = chat.get("messages", [])
            # Consider it first contact resolution if:
            # - Chat is resolved
            # - Has exactly 2 messages (user + assistant) or 3 messages (system + user + assistant)
            if chat.get("is_resolved", False):
                msg_count = len(messages)
                if msg_count == 2:
                    # Must be user then assistant
                    if (messages[0].get("role") == "user" and 
                        messages[1].get("role") == "assistant"):
                        first_contact_resolved += 1
                elif msg_count == 3:
                    # Must be system, user, assistant
                    if (messages[0].get("role") == "system" and 
                        messages[1].get("role") == "user" and 
                        messages[2].get("role") == "assistant"):
                        first_contact_resolved += 1
        
        first_contact_percent = 0.0
        if total_tickets > 0:
            first_contact_percent = (first_contact_resolved / total_tickets) * 100
        
        return {
            "total_resolved_tickets": {
                "total_tickets": total_tickets,
                "total_resolved_tickets": total_resolved_tickets
            },
            "average_resolution_time": {
                "value": round(avg_resolution_time, 2) if avg_resolution_time is not None else None,
                "unit": "hours"
            },
            "first_contact_resolution": {
                "resolved_in_first_contact": first_contact_resolved,
                "percent": round(first_contact_percent, 1)
            }
        }

    async def get_resolved_discord_chats(
        self, 
        user_id: str, 
        page: int = 1, 
        page_size: int = 10
    ) -> dict:
        """
        Get paginated resolved Discord chats for a user.
        
        Args:
            user_id: The user ID
            page: Page number (1-indexed)
            page_size: Number of items per page
            
        Returns:
            dict: Paginated chat data with metadata
        """
        db = DatabaseSession.get_db()
        
        skip = (page - 1) * page_size
        
        # Get total count
        total_count = await db[self.discord_collection].count_documents(
            {"user_id": user_id, "is_resolved": True}
        )
        
        # Get paginated chats
        cursor = (
            db[self.discord_collection]
            .find({"user_id": user_id, "is_resolved": True})
            .sort("updated_at", -1)
            .skip(skip)
            .limit(page_size)
        )
        
        chats: List[DiscordChat] = []
        async for doc in cursor:
            chats.append(DiscordChat(**doc))
        
        total_pages = (total_count + page_size - 1) // page_size  # Ceiling division
        
        return {
            "chats": [chat.model_dump() for chat in chats],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
        }

    async def get_unresolved_discord_chats(
        self, 
        user_id: str, 
        page: int = 1, 
        page_size: int = 10
    ) -> dict:
        """
        Get paginated unresolved Discord chats for a user.
        
        Args:
            user_id: The user ID
            page: Page number (1-indexed)
            page_size: Number of items per page
            
        Returns:
            dict: Paginated chat data with metadata
        """
        db = DatabaseSession.get_db()
        
        skip = (page - 1) * page_size
        
        # Get total count
        total_count = await db[self.discord_collection].count_documents(
            {"user_id": user_id, "is_resolved": False}
        )
        
        # Get paginated chats
        cursor = (
            db[self.discord_collection]
            .find({"user_id": user_id, "is_resolved": False})
            .sort("updated_at", -1)
            .skip(skip)
            .limit(page_size)
        )
        
        chats: List[DiscordChat] = []
        async for doc in cursor:
            chats.append(DiscordChat(**doc))
        
        total_pages = (total_count + page_size - 1) // page_size  # Ceiling division
        
        return {
            "chats": [chat.model_dump() for chat in chats],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
        }


analytics_service = AnalyticsService()
