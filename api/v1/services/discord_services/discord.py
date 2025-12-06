from api.v1.utils.crypto import fernet_decrypt
from api.v1.utils.exceptions import (
    AuthenticationError,
    ServerAlreadyRegisteredError,
    TokenAlreadyUsedError,
    UserNotFoundError,
    InvalidTokenError,
    DatabaseError,
)
from typing import Optional
import jwt
from api.v1.config import auth_config
from api.v1.db.session import DatabaseSession
from datetime import datetime, timezone
import logging
from api.v1.services.embed import (
    generate_text_embedding,
    search_similar_docs,
    get_openai_chat_completion_with_history,
)
from api.v1.services.chats import chat_service
from api.v1.schemas.chats import ChatMessage

logger = logging.getLogger(__name__)


async def authenticate_server(auth_data: dict) -> bool:
    """
    Authenticate the server using the provided auth_data.
    
    Args:
        auth_data: Dictionary containing authentication data
        
    Returns:
        bool: True if authentication successful, False otherwise
        
    Raises:
        AuthenticationError: Various authentication-related errors with descriptive messages
    """
    token = auth_data.get("token")
    server_id = auth_data.get("server_id")
    
    if not token or not server_id:
        logger.error("Missing required authentication data: token or server_id")
        return False

    try:
        # Decrypt the token
        decrypted_jwt_token = fernet_decrypt(token)
        if not decrypted_jwt_token:
            raise ValueError("Failed to decrypt token")

        db = DatabaseSession.get_db()
        if db is None:
            logger.error("Database connection is not available")
            raise DatabaseError("Database connection is not available")

        # Check if server is already registered in discord_servers collection
        existing_server = await db["discord_servers"].find_one(
            {"server_id": str(server_id)}
        )
        
        if existing_server:
            logger.warning(f"Server {server_id} is already registered with the bot")
            raise ServerAlreadyRegisteredError(f"Server {server_id} is already registered with the bot")

        # Check if token is already used
        invalid_tokens_collection = db["invalid_tokens"]
        invalid_token_record = await invalid_tokens_collection.find_one(
            {"token": decrypted_jwt_token}
        )
        
        if invalid_token_record:
            logger.warning("JWT token has already been used")
            raise TokenAlreadyUsedError("JWT token has already been used")

        # Decode and validate JWT token
        payload = jwt.decode(
            decrypted_jwt_token, 
            auth_config.JWT_SECRET_KEY,
            algorithms=["HS256"]
        )
        
        user_id = payload.get("user_id")
        if not user_id:
            logger.error("JWT payload missing user_id")
            return False

        # Find user in database
        user_record = await db["users"].find_one({"user_id": str(user_id)})
        if not user_record:
            logger.error(f"User {user_id} not found in database")
            raise UserNotFoundError(f"User {user_id} not found in database")

        # Create server document for discord_servers collection
        server_document = {
            "user_id": str(user_id),
            "server_id": str(server_id),
            "server_name": auth_data.get("server_name", ""),
            "owner_id": auth_data.get("owner_id"),
            "owner_username": auth_data.get("owner_username"),
            "member_count": auth_data.get("member_count"),
            "forums": auth_data.get("forums", []),
            "selected_forums": auth_data.get("selected_forums", []),
            "bot_permissions": {
                "permissions_value": auth_data.get("bot_permissions", {}).get("permissions_value"),
                "is_authenticated": True,  # Set to True since we're authenticating
                "admin": auth_data.get("bot_permissions", {}).get("admin", False)
            },
            "joined_at": datetime.now(timezone.utc)
        }

        # Insert server into discord_servers collection
        await db["discord_servers"].insert_one(server_document)

        # Update user's updated_at timestamp
        await db["users"].update_one(
            {"user_id": str(user_id)},
            {"$set": {"updated_at": datetime.now(timezone.utc)}}
        )

        # Add used token to invalid tokens collection
        await invalid_tokens_collection.insert_one({
            "token": decrypted_jwt_token, 
            "added_at": datetime.now(timezone.utc),
            "user_id": str(user_id),
            "server_id": str(server_id)
        })

        logger.info(f"Successfully authenticated server {server_id} for user {user_id}")
        return True

    except (ServerAlreadyRegisteredError, TokenAlreadyUsedError, 
            UserNotFoundError, InvalidTokenError, DatabaseError):
        raise  # Re-raise specific authentication errors
    except jwt.ExpiredSignatureError:
        logger.error("JWT token has expired")
        raise InvalidTokenError("JWT token has expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"Invalid JWT token: {e}")
        raise InvalidTokenError(f"Invalid JWT token: {e}")
    except ValueError as e:
        logger.error(f"Value error during authentication: {e}")
        raise InvalidTokenError(f"Token decryption failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during server authentication: {e}")
        raise AuthenticationError(f"Authentication failed: {str(e)}")


async def is_server_registered(server_id: str) -> bool:
    """
    Check if a server is already registered in discord_servers collection.
    
    Args:
        server_id: The Discord server ID to check
        
    Returns:
        bool: True if server is registered, False otherwise
    """
    try:
        db = DatabaseSession.get_db()
        if db is None:
            return False
            
        existing_server = await db["discord_servers"].find_one(
            {"server_id": str(server_id)}
        )
        
        return existing_server is not None
    except Exception as e:
        logger.error(f"Error checking if server is registered: {e}")
        return False


async def get_user_servers(user_id: str) -> list:
    """
    Get all servers registered by a user.
    
    Args:
        user_id: The user ID to look up
        
    Returns:
        list: List of server documents
    """
    try:
        db = DatabaseSession.get_db()
        if db is None:
            return []
            
        servers = await db["discord_servers"].find(
            {"user_id": str(user_id)},
            {"_id": 0, "server_id": 1, "server_name": 1, "member_count": 1, "forums": 1, "selected_forums": 1}
        ).to_list(length=None)
        
        return servers
    except Exception as e:
        logger.error(f"Error getting user servers: {e}")
        return []


async def update_selected_forums(user_id: str, server_id: str, selected_forums: list) -> bool:
    """
    Update the selected_forums list for a specific server.
    
    Args:
        user_id: The user ID who owns the server registration
        server_id: The Discord server ID to update
        selected_forums: List of forum dictionaries with forum_id and forum_name
        
    Returns:
        bool: True if update successful, False otherwise
    """
    try:
        db = DatabaseSession.get_db()
        if db is None:
            logger.error("Database connection is None")
            return False
            
        # Update the selected_forums field for the server
        result = await db["discord_servers"].update_one(
            {"user_id": str(user_id), "server_id": str(server_id)},
            {"$set": {
                "selected_forums": selected_forums,
                "updated_at": datetime.now(timezone.utc)
            }}
        )
        
        if result.matched_count == 0:
            logger.warning(f"No server found for user_id={user_id}, server_id={server_id}")
            return False
            
        logger.info(f"Successfully updated selected_forums for server {server_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error updating selected forums: {e}")
        return False


async def refresh_forums_list(server_id: str, guild) -> bool:
    """
    Refresh the complete forums list for a server by querying all forum channels.
    
    Args:
        server_id: The Discord server ID
        guild: The Discord guild object
        
    Returns:
        bool: True if update successful, False otherwise
    """
    try:
        db = DatabaseSession.get_db()
        if db is None:
            logger.error("Database connection is None")
            return False
        
        # Collect all current forum channels
        forums = []
        for channel in guild.channels:
            if str(channel.type) == "forum":  # ChannelType.forum
                forums.append({
                    "forum_id": str(channel.id),
                    "forum_name": channel.name,
                })
        
        # Update the forums list in the database
        result = await db["discord_servers"].update_one(
            {"server_id": str(server_id)},
            {"$set": {
                "forums": forums,
                "updated_at": datetime.now(timezone.utc)
            }}
        )
        
        if result.matched_count == 0:
            logger.warning(f"No server found for server_id={server_id}")
            return False
            
        logger.info(f"Successfully refreshed forums list for server {server_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error refreshing forums list: {e}")
        return False


async def remove_forum_from_selected(server_id: str, forum_id: str) -> bool:
    """
    Remove a specific forum from the selected_forums list.
    
    Args:
        server_id: The Discord server ID
        forum_id: The forum channel ID to remove
        
    Returns:
        bool: True if update successful, False otherwise
    """
    try:
        db = DatabaseSession.get_db()
        if db is None:
            logger.error("Database connection is None")
            return False
        
        # Pull the forum from selected_forums array
        result = await db["discord_servers"].update_one(
            {"server_id": str(server_id)},
            {
                "$pull": {"selected_forums": {"forum_id": str(forum_id)}},
                "$set": {"updated_at": datetime.now(timezone.utc)}
            }
        )
        
        if result.matched_count == 0:
            logger.warning(f"No server found for server_id={server_id}")
            return False
            
        logger.info(f"Successfully removed forum {forum_id} from selected_forums for server {server_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error removing forum from selected_forums: {e}")
        return False
    
async def send_message(
    messages, 
    user_id: str, 
    server_id: str, 
    thread_id: Optional[str] = None,
    channel_id: Optional[str] = None
) -> str:
    """
    Enhanced Discord message handler with chat history management.
    
    - Retrieves existing chat if thread_id is provided
    - Creates new chat if thread is new
    - Includes full conversation history in context
    - Stores user message and bot response after completion
    
    Args:
        messages: List like [{"type": "text", "text": "your question"}]
        user_id: The user's ID to scope search
        server_id: The Discord server ID to scope search
        thread_id: Discord thread ID for conversation tracking
        channel_id: Discord channel ID
        
    Returns:
        str: The complete bot response
    """
    collected_response = []
    chat_id = None
    
    try:
        user_query = messages[0]["text"]
        
        # 1) Check for existing chat in this thread
        existing_chat = None
        if thread_id:
            existing_chat = await chat_service.get_discord_chat_by_thread(
                thread_id=thread_id, user_id=user_id
            )
            if existing_chat:
                chat_id = existing_chat.chat_id
                logger.info(f"Found existing chat {chat_id} for thread {thread_id}")
        
        # 2) Perform vector search for context
        query_embedding = await generate_text_embedding(user_query)
        top_docs = await search_similar_docs(
            query_embedding, 
            top_k=4, 
            user_id=user_id, 
            server_id=server_id,
        )
        
        if not top_docs:
            context = "No sufficiently relevant context found in the knowledge base."
            logger.info(f"No documents met similarity threshold for Discord query: {user_query[:50]}...")
        else:
            context = "\n\n".join([doc.get("text", "") for doc in top_docs])
            logger.info(f"Retrieved {len(top_docs)} documents with scores: {[doc.get('score', 0) for doc in top_docs]}")
        
        # Extract sources from retrieved documents
        sources = list({doc.get("doc_url") for doc in top_docs if doc.get("doc_url")})
        
        # 3) Build messages array with history
        msg_array = []
        
        # System message with context
        system_prompt = (
            "You are a helpful AI assistant for SaaS documentation. "
            "Use the below context to answer the user's question clearly and accurately. "
            "If the answer isn't in the docs, say so.\n\n"
            f"### Context:\n{context}"
        )
        msg_array.append({"role": "system", "content": system_prompt})
        
        # Add conversation history if continuing a thread
        if existing_chat and existing_chat.messages:
            for msg in existing_chat.messages:
                msg_array.append({
                    "role": msg.role,
                    "content": msg.content
                })
            logger.info(f"Added {len(existing_chat.messages)} historical messages to context")
        
        # Add current user query
        msg_array.append({"role": "user", "content": user_query})
        
        # 4) Get completion with full context
        async for chunk in get_openai_chat_completion_with_history(msg_array):
            collected_response.append(chunk)
        
        full_response = "".join(collected_response)
        
        # 5) Store chat messages
        try:
            if not chat_id:
                # Create new chat for this thread
                chat_id = await chat_service.create_discord_chat(
                    user_id=user_id,
                    server_id=server_id,
                    channel_id=channel_id,
                    thread_id=thread_id,
                )
                logger.info(f"Created new Discord chat {chat_id} for thread {thread_id}")
            
            # Store user message
            user_msg = ChatMessage(role="user", content=user_query)
            await chat_service.append_discord_message(chat_id=chat_id, message=user_msg)
            
            # Store assistant response with sources
            assistant_msg = ChatMessage(
                role="assistant",
                content=full_response,
                sources=sources if sources else None
            )
            await chat_service.append_discord_message(chat_id=chat_id, message=assistant_msg)
            
            logger.info(f"Successfully stored Discord messages for chat {chat_id}")
        except Exception as store_error:
            logger.error(f"Failed to store Discord chat messages: {store_error}", exc_info=True)
            # Don't fail the response if storage fails
        
        return full_response or ""
        
    except Exception as e:
        logger.error(f"Error in send_message: {e}", exc_info=True)
        return f"⚠️ Error: {e}"
