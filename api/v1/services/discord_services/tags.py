import json
import logging
from typing import List, Dict, Any
import discord
from discord import ChannelType

from api.v1.db.session import DatabaseSession
from api.v1.services.embed import get_openai_chat_completion_with_history
from api.v1.utils.prompts import forum_post_categorization_prompt

logger = logging.getLogger(__name__)


async def categorize_forum_post_with_llm(
    thread_title: str,
    thread_content: str,
    available_tags: List[Dict[str, Any]]
) -> List[str]:
    """
    Use LLM to categorize a forum post based on its title, content, and available tags.
    """
    # Validation
    if not thread_title or not isinstance(thread_title, str):
        logger.warning("Invalid thread_title provided for categorization")
        return []
    
    if not thread_content:
        thread_content = ""  # Allow empty content
    
    if not available_tags or not isinstance(available_tags, list):
        logger.info("No tags available for categorization")
        return []
    
    # Prepare tags for the prompt (simplified format)
    tags_for_prompt = [
        {
            "tag_id": tag.get("tag_id"),
            "tag_name": tag.get("tag_name"),
            "tag_emoji": tag.get("tag_emoji")
        }
        for tag in available_tags
        if tag.get("tag_id") and tag.get("tag_name")
    ]
    
    if not tags_for_prompt:
        logger.info("No valid tags to use for categorization")
        return []
    
    # Build the user message
    user_message = f"""Available Tags: {json.dumps(tags_for_prompt)}

Thread Title: {thread_title}

Thread Content: {thread_content if thread_content.strip() else "(No content provided)"}"""
    
    messages = [
        {"role": "system", "content": forum_post_categorization_prompt},
        {"role": "user", "content": user_message}
    ]
    
    try:
        # Request JSON response format
        response = await get_openai_chat_completion_with_history(
            messages=messages,
            response_format={"type": "json_object"}
        )
        
        # Parse the JSON response
        result = json.loads(response)
        tag_ids = result.get("tag_ids", [])
        
        # Validate that returned tag_ids exist in available_tags
        valid_tag_ids = {tag.get("tag_id") for tag in available_tags}
        validated_tag_ids = [
            tag_id for tag_id in tag_ids 
            if tag_id in valid_tag_ids
        ]
        
        # Limit to 3 tags maximum
        validated_tag_ids = validated_tag_ids[:3]
        
        logger.info(f"LLM categorization result: {validated_tag_ids} for thread '{thread_title[:50]}'")
        return validated_tag_ids
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM categorization response as JSON: {e}")
        return []
    except Exception as e:
        logger.error(f"Error in forum post categorization: {e}", exc_info=True)
        return []


async def get_thread_starter_content(thread: discord.Thread) -> str:
    """
    Fetch the starter message content from a forum thread.
    """
    try:
        # The thread's starter_message might be cached or we need to fetch it
        if thread.starter_message:
            return thread.starter_message.content or ""
        else:
            # Fetch the first message in the thread
            async for message in thread.history(limit=1, oldest_first=True):
                return message.content or ""
            return ""
    except discord.Forbidden:
        logger.warning(f"No permission to read messages in thread {thread.id}")
        return ""
    except Exception as e:
        logger.warning(f"Could not fetch thread starter message: {e}")
        return ""


async def map_tag_ids_to_forum_tags(
    tag_ids: List[str],
    forum_channel: discord.ForumChannel
) -> List[discord.ForumTag]:
    """
    Map tag IDs to actual Discord ForumTag objects from a forum channel.
    """
    if not hasattr(forum_channel, 'available_tags') or not forum_channel.available_tags:
        logger.warning(f"Forum channel {forum_channel.id} has no available_tags")
        return []
    
    # Create a mapping of tag_id to ForumTag objects
    tag_id_to_tag = {str(tag.id): tag for tag in forum_channel.available_tags}
    
    # Get the ForumTag objects that match the suggested tag_ids
    tags_to_apply = []
    for tag_id in tag_ids:
        if tag_id in tag_id_to_tag:
            tags_to_apply.append(tag_id_to_tag[tag_id])
        else:
            logger.warning(f"Tag ID {tag_id} not found in forum channel {forum_channel.id}")
    
    return tags_to_apply


async def apply_tags_to_thread(
    thread: discord.Thread,
    tags_to_apply: List[discord.ForumTag]
) -> bool:
    """
    Apply tags to a Discord forum thread, respecting existing tags and Discord's limits.
    """
    if not tags_to_apply:
        logger.warning(f"No tags to apply to thread {thread.id}")
        return False
    
    try:
        # Combine with existing tags (if any) and ensure uniqueness
        existing_tags = list(thread.applied_tags) if thread.applied_tags else []
        existing_tag_ids = {str(tag.id) for tag in existing_tags}
        
        # Only add tags that aren't already applied
        new_tags = [tag for tag in tags_to_apply if str(tag.id) not in existing_tag_ids]
        
        if new_tags:
            combined_tags = existing_tags + new_tags
            # Discord has a limit of 5 tags per thread
            combined_tags = combined_tags[:5]
            
            await thread.edit(applied_tags=combined_tags)
            tag_names = [tag.name for tag in new_tags]
            logger.info(f"✅ Auto-tagged thread '{thread.name}' with: {tag_names}")
            return True
        else:
            logger.info(f"Thread '{thread.name}' already has suggested tags applied")
            return False
            
    except discord.Forbidden:
        logger.error(f"Bot lacks permission to edit tags on thread {thread.id}")
        return False
    except discord.HTTPException as e:
        logger.error(f"Failed to apply tags to thread {thread.id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error applying tags to thread {thread.id}: {e}", exc_info=True)
        return False


async def auto_tag_forum_thread(thread: discord.Thread) -> None:
    """
    Main function to automatically categorize and tag a new forum thread.
    
    This function orchestrates the entire auto-tagging workflow:
    1. Validates the thread is in a forum channel
    2. Checks if the server is registered
    3. Fetches available tags from database
    4. Extracts thread title and content
    5. Uses LLM to categorize the post
    6. Maps tag IDs to Discord ForumTag objects
    7. Applies the tags to the thread
    
    Args:
        thread: The Discord thread object that was just created
    """
    try:
        # Only process threads in forum channels
        if not thread.parent or thread.parent.type != ChannelType.forum:
            return
        
        guild = thread.guild
        if not guild:
            return
        
        server_id = str(guild.id)
        
        # Check if the server is registered
        db = DatabaseSession.get_db()
        if db is None:
            logger.warning("Database connection is None")
            return
            
        server = await db["discord_servers"].find_one({"server_id": server_id})
        if not server:
            # Server not registered, skip auto-tagging
            logger.debug(f"Server {server_id} not registered, skipping auto-tag for thread {thread.name}")
            return
        
        # Get available tags from database
        available_tags = server.get("tags", [])
        if not available_tags:
            logger.info(f"No tags available for server {server_id}, skipping auto-tag for thread {thread.name}")
            return
        
        # Extract thread information
        thread_title = thread.name
        thread_content = await get_thread_starter_content(thread)
        
        logger.info(f"🤖 Categorizing forum post: '{thread_title[:50]}...' in server {server_id}")
        
        # Categorize using LLM
        suggested_tag_ids = await categorize_forum_post_with_llm(
            thread_title=thread_title,
            thread_content=thread_content,
            available_tags=available_tags
        )
        
        if not suggested_tag_ids:
            logger.info(f"No tags suggested for thread '{thread_title}' by LLM")
            return
        
        # Map tag IDs to Discord ForumTag objects
        forum_channel = thread.parent
        tags_to_apply = await map_tag_ids_to_forum_tags(suggested_tag_ids, forum_channel)
        
        if not tags_to_apply:
            logger.warning(f"No valid ForumTag objects found for suggested tag_ids: {suggested_tag_ids}")
            return
        
        # Apply the tags to the thread
        await apply_tags_to_thread(thread, tags_to_apply)
        
    except Exception as e:
        logger.error(f"Error in auto_tag_forum_thread: {e}", exc_info=True)
