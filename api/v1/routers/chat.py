from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from typing import List
import logging

from api.v1.services.auth_services.auth import AuthService
from api.v1.utils.csrf import csrf_verification
from api.v1.services.chats import chat_service
from api.v1.schemas.chats import PlaygroundChat, ChatRequest

router = APIRouter()
auth_service = AuthService()
logger = logging.getLogger(__name__)


@router.post("/chat")
async def chat(
	req: ChatRequest,
	user=Depends(auth_service.get_current_user),
	_: bool = Depends(csrf_verification.verify_csrf),
):
	"""
	Chat endpoint with complete history management:
	- Creates new chat or continues existing chat
	- Performs vector search + streamed GPT answer (SSE)
	- Stores complete conversation history after streaming
	"""
	
	if not req.query or not req.server_id:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="query and server_id are required",
		)

	user_id = user["user_id"]
	
	return StreamingResponse(
		chat_service.handle_playground_chat_stream(
			query=req.query,
			user_id=user_id,
			server_id=req.server_id,
			chat_id=req.chat_id,
			top_k=req.top_k,
		),
		media_type="text/event-stream",
		headers={
			# Helpful for proxies
			"Cache-Control": "no-cache",
			"Connection": "keep-alive",
		},
	)


@router.get("/chat_history", response_model=List[PlaygroundChat])
async def get_chat_history(
	server_id: str,
	limit: int = 20,
	user=Depends(auth_service.get_current_user),
):
	"""Return playground chats for the current user filtered by server_id, newest first."""
	try:
		if not server_id:
			raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="server_id is required")
		chats = await chat_service.get_playground_chat_history(user_id=user["user_id"], server_id=server_id, limit=limit)
		return chats
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"Error fetching chat history: {e}", exc_info=True)
		raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch chat history")


@router.get("/{chat_id}", response_model=PlaygroundChat)
async def get_chat(
	chat_id: str,
	user=Depends(auth_service.get_current_user),
):
	"""
	Retrieve a specific playground chat by its chat_id.
	Only returns the chat if it belongs to the authenticated user.
	"""
	try:
		chat = await chat_service.get_playground_chat_by_id(
			chat_id=chat_id, user_id=user["user_id"]
		)
		if not chat:
			raise HTTPException(
				status_code=status.HTTP_404_NOT_FOUND,
				detail=f"Chat {chat_id} not found or unauthorized"
			)
		return chat
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"Error fetching chat {chat_id}: {e}", exc_info=True)
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail="Failed to fetch chat"
		)