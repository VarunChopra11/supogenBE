from fastapi import APIRouter, Depends, HTTPException, status
import logging

from api.v1.services.auth_services.auth import AuthService
from api.v1.utils.csrf import csrf_verification
from api.v1.services.chunk import chunk_service
from api.v1.services.documents import document_service
from api.v1.schemas.chunks import (
    MarkdownProcessRequest, 
    MarkdownProcessResponse, 
)
from api.v1.schemas.documents import DocumentModel

router = APIRouter()
auth_service = AuthService()
logger = logging.getLogger(__name__)

@router.post("/embed_docs", response_model = MarkdownProcessResponse)
async def embed_documents(
    request: MarkdownProcessRequest,
    user = Depends(auth_service.get_current_user),
    _: bool = Depends(csrf_verification.verify_csrf)
):
    """
    Process a markdown document from URL and create vector-ready chunks.
    
    - **server_id**: UUID of the server to associate with chunks
    - **markdown_url**: Public URL of the markdown document to process
    """
    try:
        # Validate request parameters
        if not request.document_url or not request.server_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="document_url and server_id are required"
            )

        # Check url not in documents already
        document = await document_service.get_document_by_url(request.document_url)
        if document:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document has already been processed."
            )

        chunks = await chunk_service.generate_and_store_chunks_from_url(
            url=request.document_url,
            user_id=user["user_id"],
            server_id=request.server_id
        )
        
        response = MarkdownProcessResponse(
            success=True,
            message="Document processed and chunks created successfully.",
            chunks_created=len(chunks)
        )

        # Insert document record
        await document_service.insert_document(
            document=request.document_url,
            user_id=user["user_id"],
            server_id=request.server_id
        )

        return response
    
    except HTTPException:
        # Re-raise HTTP exceptions as they are already properly formatted
        raise
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process document"
        )
    
@router.get("/get_documents/{server_id}", response_model = list[DocumentModel])
async def get_documents(
    server_id: str,
    user = Depends(auth_service.get_current_user),
):
    """
    Retrieve all documents associated with a specific server ID.
    
    - **server_id**: UUID of the server to fetch documents for
    """
    try:
        if not server_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="server_id is required"
            )

        documents = await document_service.get_documents_by_server(server_id)
        return documents
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving documents: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve documents"
        )