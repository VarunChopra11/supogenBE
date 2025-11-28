from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import AsyncGenerator, Set, List, Optional
import json
import logging

from api.v1.services.auth_services.auth import AuthService
from api.v1.utils.csrf import csrf_verification
from api.v1.services.embed import (
	generate_text_embedding,
	search_similar_docs,
	get_openai_chat_completion_with_history,
)
from api.v1.services.chats import chat_service
from api.v1.schemas.chats import PlaygroundChat, ChatMessage

router = APIRouter()
auth_service = AuthService()
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
	query: str = Field(..., description="User question to answer")
	server_id: str = Field(..., description="Server scope for RAG search")
	chat_id: Optional[str] = Field(None, description="Chat ID to continue existing conversation")
	top_k: int = Field(4, ge=1, le=20, description="Number of chunks to retrieve")


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
	
	# Storage for collecting the complete assistant response
	collected_response = []
	final_chat_id = req.chat_id
	
	async def event_stream() -> AsyncGenerator[str, None]:
		nonlocal collected_response, final_chat_id
		
		try:
			# 1) Get or create chat
			existing_chat = None
			if final_chat_id:
				existing_chat = await chat_service.get_playground_chat_by_id(
					chat_id=final_chat_id, user_id=user_id
				)
				if not existing_chat:
					raise HTTPException(
						status_code=status.HTTP_404_NOT_FOUND,
						detail=f"Chat {final_chat_id} not found or unauthorized",
					)
				# Validate server_id matches
				if existing_chat.server_id != req.server_id:
					raise HTTPException(
						status_code=status.HTTP_400_BAD_REQUEST,
						detail="server_id mismatch with existing chat",
					)
			
			# 2) Embed the query
			query_embedding = await generate_text_embedding(req.query)

			# 3) Vector search scoped by user and server
			top_docs = await search_similar_docs(
				query_embedding=query_embedding,
				user_id=user_id,
				server_id=req.server_id,
				top_k=req.top_k,
			)

			sources: Set[str] = {d.get("doc_url") for d in top_docs if d.get("doc_url")}

			# Stream sources first so client can render citations early
			yield "event: sources\n" + f"data: {json.dumps(list(sources))}\n\n"

			# 4) Build context from retrieved documents
			context = "\n\n".join([d.get("text", "") for d in top_docs])
			if not context.strip():
				context = "No relevant context retrieved."

			# 5) Build messages array with complete history
			messages = []
			
			# System message with context
			system_prompt = (
				"You are a helpful AI assistant specialized in explaining SaaS API documentation. "
				"Use the context below to answer the user's question as precisely as possible. "
				"If the answer isn't explicitly in the context, say \"I couldn't find that information.\"\n\n"
				f"### Context:\n{context}"
			)
			messages.append({"role": "system", "content": system_prompt})
			
			# Add conversation history if continuing a chat
			if existing_chat and existing_chat.messages:
				for msg in existing_chat.messages:
					messages.append({
						"role": msg.role,
						"content": msg.content
					})
			
			# Add current user query
			messages.append({"role": "user", "content": req.query})

			# 6) Stream model output with full context
			async for delta in get_openai_chat_completion_with_history(messages):
				collected_response.append(delta)
				# Send as SSE data frames
				yield f"data: {json.dumps(delta)}\n\n"

			# 7) Create chat_id if new conversation
			if not final_chat_id:
				final_chat_id = await chat_service.create_playground_chat(
					user_id=user_id,
					server_id=req.server_id,
				)
			
			# Send the chat_id to the client
			yield "event: chat_id\n" + f"data: {json.dumps({'chat_id': final_chat_id})}\n\n"
			
			# Indicate completion
			yield "event: done\ndata: null\n\n"

		except HTTPException:
			raise
		except Exception as e:
			logger.error(f"Chat streaming error: {str(e)}", exc_info=True)
			# Surface the error to the client as an SSE error event
			yield "event: error\n" + f"data: {json.dumps({'message': 'Internal server error'})}\n\n"
		
		finally:
			# 8) Store messages in database after streaming completes
			if final_chat_id and collected_response:
				try:
					complete_response = "".join(collected_response)
					
					# Store user message
					user_msg = ChatMessage(role="user", content=req.query)
					await chat_service.append_playground_message(
						chat_id=final_chat_id, message=user_msg
					)
					
					# Store assistant response with sources
					assistant_msg = ChatMessage(
						role="assistant",
						content=complete_response,
						sources=list(sources) if sources else None
					)
					await chat_service.append_playground_message(
						chat_id=final_chat_id, message=assistant_msg
					)
					
					logger.info(f"Successfully stored messages for chat {final_chat_id}")
				except Exception as e:
					logger.error(
						f"Failed to store chat messages for {final_chat_id}: {str(e)}", 
						exc_info=True
					)

	return StreamingResponse(
		event_stream(),
		media_type="text/event-stream",
		headers={
			# Helpful for proxies
			"Cache-Control": "no-cache",
			"Connection": "keep-alive",
		},
	)


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
