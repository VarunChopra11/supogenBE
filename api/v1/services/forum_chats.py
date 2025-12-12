import json
import uuid
import logging
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
from openai import APIError, APIConnectionError, RateLimitError

from api.v1.db.session import DatabaseSession
from api.v1.schemas.chunks import DiscordChatChunk
from api.v1.services.prompts import analyze_forum_chat_prompt
from api.v1.services.embed import generate_text_embedding, get_openai_chat_completion_with_history

logger = logging.getLogger(__name__)


class ForumChatService:
    async def get_stale_forum_chats(self, days_threshold: int = 4) -> List[dict]:
        """
        Retrieve all forum chats that haven't been updated in the specified number of days.
        These are candidates for auto-resolution and potential RAG indexing.
        """

        db = DatabaseSession.get_db()
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_threshold)
        
        # Find all forum chats older than threshold
        stale_chats = await db["forum_chats"].find(
            {"updated_at": {"$lte": cutoff_time}}
        ).to_list(length=None)
        
        return stale_chats

    def format_forum_chat_transcript(self, forum_chat: dict) -> str:
        """
        Format forum chat messages into a clean, chronological transcript for LLM analysis.
        """

        if not forum_chat or "messages" not in forum_chat:
            raise ValueError("Invalid forum chat document: missing messages")
        
        messages = forum_chat.get("messages", [])
        if not messages:
            return "Empty conversation - no messages found."
        
        thread_name = forum_chat.get("thread_name", "Unknown Thread")
        channel_name = forum_chat.get("channel_name", "Unknown Channel")
        created_at = forum_chat.get("created_at", datetime.now(timezone.utc))
        
        transcript_lines = [
            f"FORUM THREAD: {thread_name}",
            f"CHANNEL: {channel_name}",
            f"CREATED: {created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "=" * 80,
            ""
        ]
        
        # Format each message chronologically
        for msg in messages:
            username = msg.get("discord_user_name", "Unknown User")
            message_content = msg.get("message", "")
            timestamp = msg.get("created_at", datetime.now(timezone.utc))
            
            if isinstance(timestamp, datetime):
                time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
            else:
                time_str = str(timestamp)
            
            transcript_lines.append(f"[{time_str}] {username}:")
            transcript_lines.append(f"  {message_content}")
            transcript_lines.append("")
        
        return "\n".join(transcript_lines)

    async def save_forum_context_to_rag(
        self,
        summary: str,
        thread_id: str,
        server_id: str,
        channel_name: str,
        thread_name: str
    ) -> bool:
        """
        Save a forum chat summary as a context chunk in discord_context_chunks for RAG retrieval.
        Generates embedding for the summary and stores it with metadata.
        """

        try:
            embedding = await generate_text_embedding(summary)
            
            if not embedding:
                logger.error(f"Failed to generate embedding for thread {thread_id}")
                return False
            
            # Prepare context chunk document
            context_chunk = DiscordChatChunk(
                chunk_id=str(uuid.uuid4()),
                thread_id=thread_id,
                server_id=server_id,
                channel_name=channel_name,
                thread_name=thread_name,
                summary=summary,
                embedding=embedding,
                created_at=datetime.now(timezone.utc)
            )
            
            # Insert into discord_context_chunks collection
            db = DatabaseSession.get_db()
            await db["discord_context_chunks"].insert_one(context_chunk)
            
            logger.info(f"Successfully saved forum context to RAG for thread {thread_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save forum context to RAG for thread {thread_id}: {e}", exc_info=True)
            return False

    async def delete_forum_chat(self, thread_id: str) -> bool:
        """
        Delete a forum chat document by thread_id.
        Used after successful resolution and optional RAG storage.
        """

        try:
            db = DatabaseSession.get_db()
            result = await db["forum_chats"].delete_one({"thread_id": thread_id})
            
            if result.deleted_count > 0:
                logger.info(f"Successfully deleted forum chat for thread {thread_id}")
                return True
            else:
                logger.warning(f"No forum chat found to delete for thread {thread_id}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to delete forum chat for thread {thread_id}: {e}", exc_info=True)
            return False
        
    async def analyze_forum_chat_with_llm(transcript: str) -> Dict[str, Any]:
        """
        Analyze a forum chat transcript using LLM to determine if it's solved,
        generate a summary, and decide if it should be added to RAG.
        """
        
        if not transcript or not isinstance(transcript, str):
            raise ValueError("Transcript must be a non-empty string")
        
        # Comprehensive prompt for LLM analysis
        system_prompt = analyze_forum_chat_prompt

        user_prompt = f"TRANSCRIPT:\n\n{transcript}\n\nProvide your analysis as a JSON object:"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "solved_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "is_solved": {"type": "boolean"},
                        "summary": {"type": "string"},
                        "to_rag": {"type": "boolean"}
                    },
                    "required": ["is_solved", "summary", "to_rag"],
                    "additionalProperties": False
                }
            }
        }
        
        try:
            response_text = await get_openai_chat_completion_with_history(
                messages=messages,
                stream=False,
                response_format=response_format
            )
            
            # Parse JSON response
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as e:
                raise ValueError(f"LLM returned invalid JSON: {e}") from e
            
            # Validate schema
            required_fields = {"is_solved", "summary", "to_rag"}
            if not required_fields.issubset(result.keys()):
                missing = required_fields - result.keys()
                raise ValueError(f"LLM response missing required fields: {missing}")
            
            # Validate types
            if not isinstance(result["is_solved"], bool):
                raise ValueError("Field 'is_solved' must be a boolean")
            if not isinstance(result["summary"], str) or len(result["summary"]) < 30:
                raise ValueError("Field 'summary' must be a non-empty string with at least 30 characters")
            if not isinstance(result["to_rag"], bool):
                raise ValueError("Field 'to_rag' must be a boolean")
            
            return result
            
        except (RateLimitError, APIConnectionError, APIError) as e:
            raise RuntimeError(f"OpenAI API error during forum analysis: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Unexpected error analyzing forum chat: {e}") from e
        
    async def process_forum_chat(self, forum_chat: dict) -> dict:
        """
        Process a single forum chat: analyze with LLM, save to RAG if needed, delete if resolved.
        """
        
        thread_id = forum_chat.get("thread_id", "unknown")
        server_id = forum_chat.get("server_id", "")
        channel_name = forum_chat.get("channel_name", "")
        thread_name = forum_chat.get("thread_name", "")
        
        result = {
            "thread_id": thread_id,
            "status": "pending",
            "action_taken": [],
            "error": None
        }
        
        try:
            # Step 1: Format the chat transcript
            logger.info(f"Processing forum chat: {thread_id} in {channel_name}/{thread_name}")
            
            try:
                transcript = self.format_forum_chat_transcript(forum_chat)
            except Exception as e:
                logger.error(f"Failed to format transcript for thread {thread_id}: {e}")
                result["status"] = "error"
                result["error"] = f"Transcript formatting failed: {str(e)}"
                return result
            
            # Step 2: Analyze with LLM
            try:
                analysis = await self.analyze_forum_chat_with_llm(transcript)
                logger.info(
                    f"LLM analysis for thread {thread_id}: "
                    f"is_solved={analysis['is_solved']}, to_rag={analysis['to_rag']}"
                )
            except Exception as e:
                logger.error(f"LLM analysis failed for thread {thread_id}: {e}", exc_info=True)
                result["status"] = "error"
                result["error"] = f"LLM analysis failed: {str(e)}"
                return result
            
            # Step 3: Save to RAG if indicated and solved
            if analysis["to_rag"] and analysis["is_solved"]:
                try:
                    saved = await self.save_forum_context_to_rag(
                        summary=analysis["summary"],
                        thread_id=thread_id,
                        server_id=server_id,
                        channel_name=channel_name,
                        thread_name=thread_name
                    )
                    
                    if saved:
                        result["action_taken"].append("saved_to_rag")
                        logger.info(f"Saved thread {thread_id} to RAG context")
                    else:
                        logger.warning(f"Failed to save thread {thread_id} to RAG")
                        result["error"] = "RAG save failed"
                except Exception as e:
                    logger.error(f"Error saving to RAG for thread {thread_id}: {e}", exc_info=True)
                    result["error"] = f"RAG save error: {str(e)}"
            
            # Step 4: Delete if solved
            if analysis["is_solved"]:
                try:
                    deleted = await self.delete_forum_chat(thread_id)
                    
                    if deleted:
                        result["action_taken"].append("deleted")
                        result["status"] = "resolved"
                        logger.info(f"Deleted resolved forum chat: {thread_id}")
                    else:
                        logger.warning(f"Failed to delete forum chat: {thread_id}")
                        result["status"] = "partial"
                        result["error"] = "Deletion failed"
                except Exception as e:
                    logger.error(f"Error deleting forum chat {thread_id}: {e}", exc_info=True)
                    result["status"] = "partial"
                    result["error"] = f"Deletion error: {str(e)}"
            else:
                # Not solved - leave as is for future processing
                result["status"] = "not_resolved"
                result["action_taken"].append("kept_for_future")
                logger.info(f"Forum chat {thread_id} not resolved, keeping for future auto-resolve")
            
            return result
            
        except Exception as e:
            logger.error(f"Unexpected error processing forum chat {thread_id}: {e}", exc_info=True)
            result["status"] = "error"
            result["error"] = f"Unexpected error: {str(e)}"
            return result
        
forum_chat_service = ForumChatService()