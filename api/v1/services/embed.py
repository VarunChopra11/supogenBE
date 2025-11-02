from typing import Optional, List, Dict, Any, AsyncGenerator
from dotenv import load_dotenv
from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError
from api.v1.db.session import DatabaseSession
from api.v1.config import ai_config

load_dotenv(override=True)

try:
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
        raise APIError("Rate limit exceeded. Please try again later.") from e
    except APIConnectionError as e:
        raise APIError("Connection to OpenAI failed. Check your internet connection.") from e
    except APIError as e:
        raise APIError(f"OpenAI API error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error generating embedding: {e}") from e


async def get_openai_chat_completion(prompt: str) -> AsyncGenerator[str, None]:
    """Stream GPT-4o-mini chat completions asynchronously."""
    if not prompt or not isinstance(prompt, str):
        raise ValueError("Prompt must be a non-empty string")

    try:
        stream = await async_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt.strip()}],
            temperature=0.2,
            max_tokens=600,
            stream=True
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except RateLimitError as e:
        raise APIError("Rate limit exceeded. Please try again later.") from e
    except APIConnectionError as e:
        raise APIError("Connection to OpenAI failed. Check your internet connection.") from e
    except APIError as e:
        raise APIError(f"OpenAI API error: {e}") from e
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
) -> List[Dict[str, Any]]:
    """
    Perform MongoDB Atlas vector search for similar documents using Motor's async cursor.
    Returns a list of result documents filtered by user_id and server_id.
    """
    if not query_embedding or not isinstance(query_embedding, list):
        raise ValueError("Query embedding must be a non-empty list of floats")

    pipeline = [
        {
            "$vectorSearch": {
                "index": "chunks_vector_index",
                "path": "embedding",
                "queryVector": query_embedding,
                "limit": top_k,            # required by Atlas
                "numCandidates": 100,      # tune as needed
                "filter": {
                    "user_id": user_id,
                    "server_id": server_id
                }
            }
        }
    ]
    db = DatabaseSession.get_db()
    if db is None:
        raise RuntimeError("Database connection not available")

    cursor = db["embedded_documents"].aggregate(pipeline)
    docs_list = await cursor.to_list(length=top_k)
    return docs_list
