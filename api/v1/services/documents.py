from api.v1.db.session import DatabaseSession
from api.v1.schemas.documents import DocumentModel
from datetime import datetime, timezone
import uuid
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

class DocumentService:
    async def insert_document(self, document: str, user_id: str, server_id: str) -> None:
        """Insert embedding records into MongoDB collection."""
        try:
            if not document:
                logger.warning("Attempted to insert empty document")
                return
            
            if not user_id or not server_id:
                logger.error("Missing required parameters: user_id or server_id")
                return

            db = DatabaseSession.get_db()
            if not db:
                logger.error("Database connection not available")
                return

            document = DocumentModel(
                document_id=str(uuid.uuid4()),
                user_id=user_id,
                server_id=server_id,
                document_url=document,
                created_at=datetime.now(timezone.utc)
            ).model_dump()

            await db["documents"].insert_one(document)
            logger.info(f"Document inserted successfully for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error inserting document: {str(e)}")
            raise
    
    async def get_documents_by_server(self, server_id: str) -> List[DocumentModel]:
        """Retrieve documents associated with a specific server ID."""
        try:
            if not server_id:
                logger.warning("Empty server_id provided")
                return []

            db = DatabaseSession.get_db()
            if not db:
                logger.error("Database connection not available")
                return []

            documents_cursor = db["documents"].find({"server_id": server_id})
            documents = []
            async for doc in documents_cursor:
                documents.append(DocumentModel(**doc))
            return documents
            
        except Exception as e:
            logger.error(f"Error retrieving documents for server {server_id}: {str(e)}")
            raise
    
    async def get_document_by_url(self, document_url: str) -> Optional[DocumentModel]:
        """Retrieve a document by its URL."""
        try:
            if not document_url:
                logger.warning("Empty document_url provided")
                return None

            db = DatabaseSession.get_db()
            if not db:
                logger.error("Database connection not available")
                return None

            doc = await db["documents"].find_one({"document_url": document_url})
            if doc:
                return DocumentModel(**doc)
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving document by URL {document_url}: {str(e)}")
            raise
    

document_service = DocumentService()