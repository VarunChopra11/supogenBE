import httpx
from markdown_it import MarkdownIt
import re
import uuid
from typing import List, Dict, Any
import logging
import asyncio
from datetime import datetime, timezone
from .embed import generate_text_embedding, insert_embeddings
from api.v1.config import ai_config

logger = logging.getLogger(__name__)

MAX_TOKENS = 1024
OVERLAP_TOKENS = 200


class ChunkService:
    def __init__(self):
        # Use httpx AsyncClient for async HTTP requests
        self._http_client = None
        # Initialize Firecrawl client lazily to avoid import errors if not configured
        self._firecrawl_client = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy initialization of async HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                headers={'User-Agent': 'Mozilla/5.0 (compatible; FastAPI-Markdown-Processor/1.0)'},
                timeout=30.0,
                follow_redirects=True
            )
        return self._http_client

    async def _get_firecrawl_client(self):
        """Lazy initialization of Firecrawl client."""
        if self._firecrawl_client is None:
            try:
                from firecrawl import Firecrawl
                api_key = ai_config.FIRECRAWL_API_KEY
                if not api_key:
                    raise ValueError("FIRECRAWL_API_KEY is not configured in environment variables")
                self._firecrawl_client = Firecrawl(api_key=api_key)
                logger.info("Firecrawl client initialized successfully")
            except ImportError:
                logger.error("firecrawl-py package not installed. Install with: pip install firecrawl-py")
                raise ValueError("Firecrawl package not available. Please install firecrawl-py.")
            except Exception as e:
                logger.error(f"Failed to initialize Firecrawl client: {str(e)}")
                raise
        return self._firecrawl_client

    async def scrape_url_to_markdown(self, url: str) -> str:
        """
        Scrape any URL and convert it to markdown using Firecrawl.
        
        Args:
            url: The URL to scrape
            
        Returns:
            Markdown content of the scraped page
            
        Raises:
            ValueError: If scraping fails or returns no markdown content
        """
        try:
            logger.info(f"Scraping URL with Firecrawl: {url}")
            firecrawl = await self._get_firecrawl_client()
            
            # Firecrawl's scrape method is synchronous, run in thread pool to avoid blocking
            result = await asyncio.to_thread(
                firecrawl.scrape,
                url,
                formats=["markdown"]
            )
            
            if not result.markdown or not result.markdown.strip():
                raise ValueError(f"Firecrawl returned no markdown content for URL: {url}")
            
            markdown_content = result.markdown
            
            if not markdown_content or not markdown_content.strip():
                raise ValueError(f"Firecrawl returned empty markdown content for URL: {url}")
            
            logger.info(f"Successfully scraped {len(markdown_content)} characters from {url}")
            return markdown_content
            
        except Exception as e:
            logger.error(f"Failed to scrape URL {url} with Firecrawl: {str(e)}")
            raise ValueError(f"Failed to scrape URL: {str(e)}")

    def is_markdown_url(self, url: str) -> bool:
        """
        Check if URL points to a markdown file based on extension.
        
        Args:
            url: The URL to check (can be string or HttpUrl)
            
        Returns:
            True if URL appears to be a markdown file, False otherwise
        """
        # Convert to string in case it's a Pydantic HttpUrl object
        url_str = str(url).lower()
        markdown_extensions = ['.md', '.markdown', '.mdown', '.mkd']
        return any(url_str.endswith(ext) for ext in markdown_extensions)

    async def download_markdown(self, url: str) -> str:
        """Download raw markdown text from a URL with proper error handling (async)."""
        try:
            logger.info(f"Downloading markdown from: {url}")
            client = await self._get_http_client()
            
            response = await client.get(str(url))
            response.raise_for_status()
            
            # Validate content type
            content_type = response.headers.get('content-type', '').lower()
            if 'text/markdown' not in content_type and 'text/plain' not in content_type:
                logger.warning(f"Unexpected content type: {content_type} for URL: {url}")
            
            return response.text
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error downloading markdown from {url}: {e.response.status_code}")
            raise ValueError(f"Failed to download markdown document: HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Request error downloading markdown from {url}: {str(e)}")
            raise ValueError(f"Failed to download markdown document: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error downloading markdown from {url}: {str(e)}")
            raise ValueError(f"Failed to download markdown document: {str(e)}")

    async def parse_markdown_sections(self, md_text: str) -> List[Dict[str, Any]]:
        """
        Parse markdown into sections by headings (async wrapper for CPU-bound operation).
        
        Runs the parsing in a thread pool to avoid blocking the event loop.
        """
        def _parse_sync(text: str) -> List[Dict[str, Any]]:
            """Synchronous parsing logic."""
            try:
                md = MarkdownIt()
                tokens = md.parse(text)

                sections = []
                current = None

                for i, tok in enumerate(tokens):
                    if tok.type == "heading_open":
                        if current and current["text"].strip():
                            sections.append(current)

                        level = int(tok.tag[-1])
                        heading_text = ""
                        next_tok = tokens[i + 1]
                        if next_tok.type == "inline":
                            heading_text = next_tok.content.strip()

                        # Create URL-safe anchor
                        anchor = re.sub(r"[^a-z0-9]+", "-", heading_text.lower()).strip("-")

                        current = {
                            "heading": heading_text, 
                            "level": level, 
                            "anchor": anchor, 
                            "text": ""
                        }

                    elif current and tok.type == "inline":
                        current["text"] += tok.content + "\n"
                    elif current and tok.type == "fence":
                        current["text"] += f"```{tok.info}\n{tok.content}\n```\n"

                if current and current["text"].strip():
                    sections.append(current)

                return [s for s in sections if s["text"].strip()]
            except Exception as e:
                logger.error(f"Error parsing markdown sections: {str(e)}")
                raise ValueError(f"Failed to parse markdown document: {str(e)}")
        
        # Run CPU-intensive parsing in thread pool
        return await asyncio.to_thread(_parse_sync, md_text)

    def count_tokens(self, text: str) -> int:
        """Simple token counting by whitespace splitting"""
        return len(text.split())

    async def chunk_text(self, text: str, max_tokens: int = MAX_TOKENS, overlap_tokens: int = OVERLAP_TOKENS) -> List[str]:
        """
        Split text into overlapping token chunks.
        
        Runs chunking in a thread pool to avoid blocking the event loop for large texts.
        """
        def _chunk_sync(text_content: str) -> List[str]:
            """Synchronous chunking logic."""
            try:
                # Split by sentences (simple approach)
                sentences = re.split(r"(?<=[\.\?\!])\s+", text_content)
                chunks, current, cur_tokens = [], "", 0

                for s in sentences:
                    s_tokens = self.count_tokens(s)
                    if cur_tokens + s_tokens > max_tokens:
                        if current:
                            chunks.append(current.strip())
                        # Add overlap
                        overlap = current.split()[-overlap_tokens:]
                        current = " ".join(overlap) + " " + s
                        cur_tokens = self.count_tokens(current)
                    else:
                        current += " " + s
                        cur_tokens += s_tokens

                if current.strip():
                    chunks.append(current.strip())

                return chunks
            except Exception as e:
                logger.error(f"Error chunking text: {str(e)}")
                raise ValueError(f"Failed to chunk text: {str(e)}")
        
        # Run CPU-intensive chunking in thread pool for large texts
        return await asyncio.to_thread(_chunk_sync, text)

    async def generate_and_store_chunks_from_url(self, url: str, user_id: str, server_id: str) -> List[Dict[str, Any]]:
        """
        Generate chunks from any URL and store in MongoDB with vector embeddings.
        
        For markdown URLs (.md, .markdown): Downloads directly
        For other URLs: Uses Firecrawl to scrape and convert to markdown
        
        Args:
            url: The URL to process (can be any web page, markdown file, or Pydantic HttpUrl)
            user_id: User ID for multi-tenancy scoping
            server_id: Server ID for multi-tenancy scoping
            
        Returns:
            List of chunk documents with embeddings
        """
        try:
            # Convert URL to string in case it's a Pydantic HttpUrl object
            url_str = str(url)
            
            # Determine how to get markdown content based on URL type
            if self.is_markdown_url(url_str):
                logger.info(f"Processing as markdown file: {url_str}")
                md_text = await self.download_markdown(url_str)
            else:
                logger.info(f"Processing as general URL with Firecrawl: {url_str}")
                md_text = await self.scrape_url_to_markdown(url_str)
            
            sections = await self.parse_markdown_sections(md_text)
            all_chunks = []

            for sec in sections:
                chunks = await self.chunk_text(sec["text"])
                for idx, ch in enumerate(chunks):
                    # Generate embedding for the chunk (async call)
                    embedding = await generate_text_embedding(ch)
                    
                    chunk_doc = {
                        "chunk_id": str(uuid.uuid4()),
                        "doc_url": url_str,
                        "heading": sec["heading"],
                        "anchor": sec["anchor"],
                        "level": sec["level"],
                        "chunk_index": idx,
                        "text": ch,
                        "tokens": self.count_tokens(ch),
                        "embedding": embedding,
                        "user_id": user_id,
                        "server_id": server_id,
                        "created_at": datetime.now(timezone.utc)
                    }
                    
                    all_chunks.append(chunk_doc)
            
            # Insert all chunks into MongoDB collection
            if all_chunks:
                await insert_embeddings(all_chunks)

            logger.info(f"Generated {len(all_chunks)} chunks from {url_str}")
            return all_chunks
            
        except Exception as e:
            logger.error(f"Error generating chunks from URL {url}: {str(e)}")
            raise

    async def cleanup(self):
        """Cleanup resources (close HTTP client)."""
        if self._http_client is not None:
            await self._http_client.aclose()
            logger.info("HTTP client closed successfully")

# Global instance
chunk_service = ChunkService()