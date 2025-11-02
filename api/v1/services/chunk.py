import requests
from markdown_it import MarkdownIt
import re
import uuid
from typing import List, Dict, Any
import logging
from datetime import datetime, timezone
from .embed import generate_text_embedding, insert_embeddings

logger = logging.getLogger(__name__)

MAX_TOKENS = 600
OVERLAP_TOKENS = 100


class ChunkService:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; FastAPI-Markdown-Processor/1.0)'
        })

    def download_markdown(self, url: str) -> str:
        """Download raw markdown text from a URL with proper error handling"""
        try:
            logger.info(f"Downloading markdown from: {url}")
            resp = self.session.get(str(url), timeout=30)
            resp.raise_for_status()
            
            # Validate content type
            content_type = resp.headers.get('content-type', '').lower()
            if 'text/markdown' not in content_type and 'text/plain' not in content_type:
                logger.warning(f"Unexpected content type: {content_type} for URL: {url}")
            
            return resp.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download markdown from {url}: {str(e)}")
            raise ValueError(f"Failed to download markdown document: {str(e)}")

    def parse_markdown_sections(self, md_text: str) -> List[Dict[str, Any]]:
        """Parse markdown into sections by headings"""
        try:
            md = MarkdownIt()
            tokens = md.parse(md_text)

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

    def count_tokens(self, text: str) -> int:
        """Simple token counting by whitespace splitting"""
        return len(text.split())

    def chunk_text(self, text: str, max_tokens: int = MAX_TOKENS, overlap_tokens: int = OVERLAP_TOKENS) -> List[str]:
        """Split text into overlapping token chunks"""
        try:
            # Split by sentences (simple approach)
            sentences = re.split(r"(?<=[\.\?\!])\s+", text)
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

    async def generate_and_store_chunks_from_url(self, url: str, user_id: str, server_id: str) -> List[Dict[str, Any]]:
        """Generate chunks from markdown URL and store in MongoDB with vector embeddings"""
        try:

            md_text = self.download_markdown(url)
            sections = self.parse_markdown_sections(md_text)
            all_chunks = []

            for sec in sections:
                chunks = self.chunk_text(sec["text"])
                for idx, ch in enumerate(chunks):
                    # Generate embedding for the chunk (async call)
                    embedding = await generate_text_embedding(ch)
                    
                    chunk_doc = {
                        "chunk_id": str(uuid.uuid4()),
                        "doc_url": str(url),
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

            logger.info(f"Generated {len(all_chunks)} chunks from {url}")
            return all_chunks
            
        except Exception as e:
            logger.error(f"Error generating chunks from URL {url}: {str(e)}")
            raise

# Global instance
chunk_service = ChunkService()