from typing import List, Optional
from datetime import datetime, timezone
from fastapi import HTTPException, status
import uuid
import json
import logging

from api.v1.db.session import DatabaseSession
from api.v1.utils.prompts import chat_system_prompt
from api.v1.schemas.chats import PlaygroundChat, DiscordChat, ChatMessage
from api.v1.services.embed import (
    generate_text_embedding,
    search_similar_docs,
    stream_openai_chat_completion_with_history,
)

logger = logging.getLogger(__name__)


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

    async def append_playground_message(self, chat_id: str, message: ChatMessage) -> None:
        db = DatabaseSession.get_db()
        await db[self.playground_collection].update_one(
            {"chat_id": chat_id},
            {
                "$push": {"messages": message.model_dump()},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    async def get_playground_chat_history(self, user_id: str, server_id: str, limit: int = 20) -> List[PlaygroundChat]:
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

    async def get_playground_chat_by_id(self, chat_id: str, user_id: str) -> Optional[PlaygroundChat]:
        """Get a specific playground chat by chat_id, ensuring it belongs to the user."""
        db = DatabaseSession.get_db()
        doc = await db[self.playground_collection].find_one(
            {"chat_id": chat_id, "user_id": user_id}
        )
        if doc:
            return PlaygroundChat(**doc)
        return None

    async def handle_playground_chat_stream(
        self,
        query: str,
        user_id: str,
        server_id: str,
        chat_id: Optional[str] = None,
        top_k: int = 4,
    ):
        """
        Handle the complete chat streaming process:
        - Validates existing chat if chat_id provided
        - Performs vector search for context
        - Streams OpenAI responses
        - Stores conversation history
        """
        
        collected_response = []
        final_chat_id = chat_id
        sources = set()
        
        try:
            # 1) Get or validate existing chat
            existing_chat = None
            if final_chat_id:
                existing_chat = await self.get_playground_chat_by_id(
                    chat_id=final_chat_id, user_id=user_id
                )
                if not existing_chat:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Chat {final_chat_id} not found or unauthorized",
                    )
                # Validate server_id matches
                if existing_chat.server_id != server_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="server_id mismatch with existing chat",
                    )
            
            # 2) Embed the query
            query_embedding = await generate_text_embedding(query)

            # 3) Vector search scoped by user and server
            top_docs = await search_similar_docs(
                query_embedding=query_embedding,
                user_id=user_id,
                server_id=server_id,
                top_k=top_k,
            )

            sources = {d.get("doc_url") for d in top_docs if d.get("doc_url")}

            # Stream sources first so client can render citations early
            yield "event: sources\n" + f"data: {json.dumps(list(sources))}\n\n"

            # 4) Build context from retrieved documents
            if not top_docs:
                context = "No sufficiently relevant context found in the knowledge base."
                logger.info(f"No documents met similarity threshold for query: {query[:50]}...")
            else:
                context = "\n\n".join([d.get("text", "") for d in top_docs])
                logger.info(f"Retrieved {len(top_docs)} documents with scores: {[d.get('score', 0) for d in top_docs]}")

            # 5) Build messages array with complete history
            messages = []
            
            # System message with context
            system_prompt = chat_system_prompt + f"### Context:\n{context}"
            messages.append({"role": "system", "content": system_prompt})
            
            # Add conversation history if continuing a chat
            if existing_chat and existing_chat.messages:
                for msg in existing_chat.messages:
                    messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })
            
            # Add current user query
            messages.append({"role": "user", "content": query})

            # 6) Stream model output with full context
            async for delta in stream_openai_chat_completion_with_history(messages):
                collected_response.append(delta)
                # Send as SSE data frames
                yield f"data: {json.dumps(delta)}\n\n"

            # 7) Create chat_id if new conversation
            if not final_chat_id:
                final_chat_id = await self.create_playground_chat(
                    user_id=user_id,
                    server_id=server_id,
                )
            
            # Send the chat_id to the client
            yield "event: chat_id\n" + f"data: {json.dumps({'chat_id': final_chat_id})}\n\n"
            
            # Indicate completion
            yield "event: done\ndata: null\n\n"

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Chat streaming error: {str(e)}", exc_info=True)
            # Surface the error to the client as an SSE error event
            yield "event: error\n" + f"data: {json.dumps({'message': 'Internal server error'})}\n\n"
        
        finally:
            # 8) Store messages in database after streaming completes
            if final_chat_id and collected_response:
                try:
                    complete_response = "".join(collected_response)
                    
                    # Store user message
                    user_msg = ChatMessage(role="user", content=query)
                    await self.append_playground_message(
                        chat_id=final_chat_id, message=user_msg
                    )
                    
                    # Store assistant response with sources
                    assistant_msg = ChatMessage(
                        role="assistant",
                        content=complete_response,
                        sources=list(sources) if sources else None
                    )
                    await self.append_playground_message(
                        chat_id=final_chat_id, message=assistant_msg
                    )
                    
                    logger.info(f"Successfully stored messages for chat {final_chat_id}")
                except Exception as e:
                    logger.error(
                        f"Failed to store chat messages for {final_chat_id}: {str(e)}", 
                        exc_info=True
                    )


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

    async def get_discord_chat_by_thread(self, thread_id: str, user_id: str) -> Optional[DiscordChat]:
        """Get a Discord chat by thread_id, ensuring it belongs to the user."""
        db = DatabaseSession.get_db()
        doc = await db[self.discord_collection].find_one(
            {"thread_id": str(thread_id), "user_id": user_id}
        )
        if doc:
            return DiscordChat(**doc)
        return None

    async def get_discord_chat_by_id(self, chat_id: str, user_id: str) -> Optional[DiscordChat]:
        """Get a Discord chat by chat_id, ensuring it belongs to the user."""
        db = DatabaseSession.get_db()
        doc = await db[self.discord_collection].find_one(
            {"chat_id": chat_id, "user_id": user_id}
        )
        if doc:
            return DiscordChat(**doc)
        return None

    async def mark_discord_chat_resolved(self, thread_id: str, is_resolved: bool) -> bool:
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
