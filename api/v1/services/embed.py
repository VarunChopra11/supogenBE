from typing import Optional, List, Dict, Any, AsyncGenerator
from openai import AsyncAzureOpenAI, AsyncOpenAI, APIError, APIConnectionError, RateLimitError
from dotenv import load_dotenv

from api.v1.db.session import DatabaseSession
from api.v1.config import ai_config

load_dotenv(override=True)

try:
    # Prefer Azure OpenAI if endpoint provided, else default to standard OpenAI
    if ai_config.AZURE_OPENAI_ENDPOINT:
        async_client = AsyncAzureOpenAI(
            api_key=ai_config.AZURE_OPENAI_API_KEY,
            azure_endpoint=f"{ai_config.AZURE_OPENAI_ENDPOINT}",
            api_version="2024-08-01-preview",
        )
    else:
        async_client = AsyncOpenAI(api_key=ai_config.OPENAI_API_KEY)
except Exception as e:
    raise RuntimeError(f"Failed to initialize OpenAI client: {e}")


async def generate_text_embedding(text: str) -> Optional[List[float]]:
    """Generate embeddings using OpenAI embedding model (async)."""
    if not text or not isinstance(text, str):
        raise ValueError("Input text must be a non-empty string")

    try:
        response = await async_client.embeddings.create(
            model="text-embedding-3-small",
            input=text.strip()
        )
        return response.data[0].embedding
    except RateLimitError as e:
        raise RuntimeError("Rate limit exceeded. Please try again later.") from e
    except APIConnectionError as e:
        raise RuntimeError("Connection to OpenAI failed. Check your internet connection.") from e
    except APIError as e:
        raise RuntimeError(f"OpenAI API error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error generating embedding: {e}") from e

async def stream_openai_chat_completion_with_history(
    messages: List[Dict[str, str]],
) -> AsyncGenerator[str, None]:
    """
    GPT-4o-mini chat completion with full message history.
    Provides streaming response.
    """
    if not messages or not isinstance(messages, list):
        raise ValueError("Messages must be a non-empty list")

    try:
        params = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "temperature": 0.2,
            "stream": True
        }

        response = await async_client.chat.completions.create(**params)

        async for chunk in response:
            if not chunk.choices or not chunk.choices[0].delta:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    except RateLimitError as e:
        raise RuntimeError("Rate limit exceeded. Please try again later.") from e
    except APIConnectionError as e:
        raise RuntimeError("Connection to OpenAI failed. Check your internet connection.") from e
    except APIError as e:
        raise RuntimeError(f"OpenAI API error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error in chat completion: {e}") from e


async def get_openai_chat_completion_with_history(
    messages: List[Dict[str, str]],
    response_format: dict | None = None
) -> str:
    """
    GPT-4o-mini chat completion with full message history (non-streaming).
    """
    if not messages or not isinstance(messages, list):
        raise ValueError("Messages must be a non-empty list")

    try:
        params = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "temperature": 0.2,
            "stream": False
        }
        if response_format is not None:
            params["response_format"] = response_format

        response = await async_client.chat.completions.create(**params)

        return response.choices[0].message.content

    except RateLimitError as e:
        raise RuntimeError("Rate limit exceeded. Please try again later.") from e
    except APIConnectionError as e:
        raise RuntimeError("Connection to OpenAI failed. Check your internet connection.") from e
    except APIError as e:
        raise RuntimeError(f"OpenAI API error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error in chat completion: {e}") from e


async def insert_embeddings(records: List[Dict[str, Any]]) -> None:
    """Insert embedding records into MongoDB collection."""
    db = DatabaseSession.get_db()
    if db is None:
        raise RuntimeError("Database connection not available")
    if not records:
        return
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise ValueError("Records must be a list of dictionaries")
    await db["embedded_documents"].insert_many(records, ordered=False)


async def search_similar_docs(
    query_embedding: List[float],
    user_id: str,
    server_id: str,
    top_k: int = 4,
    min_score: Optional[float] = 0.5,
) -> List[Dict[str, Any]]:
    """
    Perform MongoDB Atlas vector search for similar documents using Motor's async cursor.
    Returns a list of result documents filtered by user_id, server_id, and similarity score.
    """
    if not query_embedding or not isinstance(query_embedding, list):
        raise ValueError("Query embedding must be a non-empty list of floats")

    pipeline = [
        {
            "$vectorSearch": {
                "index": "chunks_vector_index",
                "path": "embedding",
                "queryVector": query_embedding,
                "limit": top_k,
                "numCandidates": 100,
                "filter": {
                    "user_id": user_id,
                    "server_id": server_id
                }
            }
        },
        {
            "$project": {
                "text": 1,
                "doc_url": 1,
                "user_id": 1,
                "server_id": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]
    db = DatabaseSession.get_db()
    if db is None:
        raise RuntimeError("Database connection not available")

    cursor = db["embedded_documents"].aggregate(pipeline)
    docs_list = await cursor.to_list(length=top_k)
    
    # Filter documents by minimum similarity score
    filtered_docs = [doc for doc in docs_list if doc.get("score", 0) >= min_score]
    
    return filtered_docs


async def search_similar_forum_chats(
    query_embedding: List[float],
    user_id: str,
    server_id: str,
    top_k: int = 4,
    min_score: Optional[float] = 0.5,
) -> List[Dict[str, Any]]:
    """
    Perform MongoDB Atlas vector search for similar Discord forum chat summaries.
    Returns a list of forum chat context chunks filtered by server_id and similarity score.
    """
    if not query_embedding or not isinstance(query_embedding, list):
        raise ValueError("Query embedding must be a non-empty list of floats")

    pipeline = [
        {
            "$vectorSearch": {
                "index": "discord_context_vector_index",
                "path": "embedding",
                "queryVector": query_embedding,
                "limit": top_k,
                "numCandidates": 100,
                "filter": {
                    "user_id": user_id,
                    "server_id": server_id
                }
            }
        },
        {
            "$project": {
                "summary": 1,
                "thread_name": 1,
                "channel_name": 1,
                "thread_id": 1,
                "server_id": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]
    
    db = DatabaseSession.get_db()
    if db is None:
        raise RuntimeError("Database connection not available")

    cursor = db["discord_context_chunks"].aggregate(pipeline)
    forum_chats_list = await cursor.to_list(length=top_k)
    
    # Filter forum chats by minimum similarity score
    filtered_chats = [chat for chat in forum_chats_list if chat.get("score", 0) >= min_score]
    
    return filtered_chats


async def get_context_from_sources(
    query_embedding: List[float],
    user_id: str,
    server_id: str,
    top_k: int = 4,
) -> tuple[str, set]:
    


    doc_chunks = await search_similar_docs(
        query_embedding=query_embedding,
        user_id=user_id,
        server_id=server_id,
        top_k=top_k,
    )

    forum_chunks = await search_similar_forum_chats(
        query_embedding=query_embedding,
        user_id=user_id,
        server_id=server_id,
        top_k=top_k,
    )

    sources = set()
    context_parts = []
    
    # Process document chunks
    if doc_chunks:
        doc_texts = []
        for doc in doc_chunks:
            if doc.get("text"):
                doc_texts.append(doc["text"])
            if doc.get("doc_url"):
                sources.add(doc["doc_url"])
        
        if doc_texts:
            context_parts.append("## Documentation:\n" + "\n\n".join(doc_texts))
    
    # Process forum chat chunks
    if forum_chunks:
        forum_texts = []
        for chat in forum_chunks:
            summary = chat.get("summary", "")
            thread_name = chat.get("thread_name", "Unknown Thread")
            channel_name = chat.get("channel_name", "Unknown Channel")
            
            if summary:
                forum_text = f"**Forum Thread**: {thread_name} (in #{channel_name})\n{summary}"
                forum_texts.append(forum_text)
        
        if forum_texts:
            context_parts.append("## Past Support Discussions:\n" + "\n\n".join(forum_texts))
    
    # Combine all context parts
    if context_parts:
        final_context = "\n\n".join(context_parts)
    else:
        final_context = "No sufficiently relevant context found in the knowledge base."
    
    return final_context, sources
