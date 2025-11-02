from api.v1.utils.crypto import fernet_decrypt
from typing import AsyncGenerator
import jwt
from api.v1.config import auth_config
from api.v1.db.session import DatabaseSession
from datetime import datetime, timezone
import logging
from api.v1.services.embed import (
    generate_text_embedding,
    search_similar_docs,
    get_openai_chat_completion,
)

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Base exception for authentication errors"""
    pass


class ServerAlreadyRegisteredError(AuthenticationError):
    """Raised when server is already registered with the bot"""
    pass


class TokenAlreadyUsedError(AuthenticationError):
    """Raised when JWT token has already been used"""
    pass


class UserNotFoundError(AuthenticationError):
    """Raised when user is not found in database"""
    pass


class InvalidTokenError(AuthenticationError):
    """Raised when JWT token is invalid or expired"""
    pass


class DatabaseError(AuthenticationError):
    """Raised when there's a database connection issue"""
    pass


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
            {"_id": 0, "server_id": 1, "server_name": 1, "member_count": 1}
        ).to_list(length=None)
        
        return servers
    except Exception as e:
        logger.error(f"Error getting user servers: {e}")
        return []
    
async def send_message(messages, user_id: str, server_id: str) -> str:
    """
    Backward-compatible helper that consumes the streaming generator and
    returns the full response as a single string.

    Called by Discord bot. 'messages' is a list like:
    [{"type": "text", "text": "your question"}]
    The search is scoped to the given user_id and server_id.
    """
    try:
        user_query = messages[0]["text"]
        # Build prompt via the same steps as the stream version
        query_embedding = await generate_text_embedding(user_query)
        top_docs = await search_similar_docs(
            query_embedding, top_k=4, user_id=user_id, server_id=server_id
        )
        context = "\n\n".join([doc.get("text", "") for doc in top_docs])
        prompt = f"""
        You are a helpful AI assistant for SaaS documentation.
        Use the below context to answer the user's question clearly and accurately.
        If the answer isn't in the docs, say so.

        ### Context:
        {context}

        ### Question:
        {user_query}

        Answer:
        """
        full_text = ""
        async for chunk in get_openai_chat_completion(prompt):
            full_text += chunk
        return full_text or ""
    except Exception as e:
        return f"⚠️ Error: {e}"


async def send_message_stream(messages, user_id: str, server_id: str) -> AsyncGenerator[str, None]:
    """
    Streaming version used by the Discord bot. Yields chunks of the model
    response as they arrive.

    Args:
        messages: List like [{"type": "text", "text": "..."}]
        user_id: The user's ID to scope search
        server_id: The Discord server ID to scope search
    Yields:
        str chunks of the answer.
    """
    try:
        user_query = messages[0]["text"]
        query_embedding = await generate_text_embedding(user_query)
        top_docs = await search_similar_docs(
            query_embedding, top_k=4, user_id=user_id, server_id=server_id
        )
        context = "\n\n".join([doc.get("text", "") for doc in top_docs])
        prompt = f"""
        You are a helpful AI assistant for SaaS documentation.
        Use the below context to answer the user's question clearly and accurately.
        If the answer isn't in the docs, say so.

        ### Context:
        {context}

        ### Question:
        {user_query}

        Answer:
        """
        async for chunk in get_openai_chat_completion(prompt):
            if chunk:
                yield chunk
    except Exception as e:
        # Surface the error to the user as a single chunk
        yield f"⚠️ Error: {e}"