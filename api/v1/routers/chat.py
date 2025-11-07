from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import AsyncGenerator, Set
import json
import logging

from api.v1.services.auth_services.auth import AuthService
from api.v1.utils.csrf import csrf_verification
from api.v1.services.embed import (
	generate_text_embedding,
	search_similar_docs,
	get_openai_chat_completion,
)

router = APIRouter()
auth_service = AuthService()
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
	query: str = Field(..., description="User question to answer")
	server_id: str = Field(..., description="Server scope for RAG search")
	top_k: int = Field(4, ge=1, le=20, description="Number of chunks to retrieve")


@router.post("/chat")
async def chat(
	req: ChatRequest,
	user=Depends(auth_service.get_current_user),
	_: bool = Depends(csrf_verification.verify_csrf),
):
	"""Chat endpoint: vector search + streamed GPT answer (SSE)."""

	if not req.query or not req.server_id:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="query and server_id are required",
		)

	async def event_stream() -> AsyncGenerator[str, None]:
		try:
			# 1) Embed the query
			query_embedding = await generate_text_embedding(req.query)

			# 2) Vector search scoped by user and server
			top_docs = await search_similar_docs(
				query_embedding=query_embedding,
				user_id=user["user_id"],
				server_id=req.server_id,
				top_k=req.top_k,
			)

			sources: Set[str] = {d.get("doc_url") for d in top_docs if d.get("doc_url")}

			# Stream sources first so client can render citations early
			yield "event: sources\n" + f"data: {json.dumps(list(sources))}\n\n"

			# 3) Build prompt with retrieved context
			context = "\n\n".join([d.get("text", "") for d in top_docs])
			if not context.strip():
				context = "No relevant context retrieved."

			prompt = (
				"You are a helpful AI assistant specialized in explaining SaaS API documentation. "
				"Use the context below to answer the user's question as precisely as possible. "
				"If the answer isn't explicitly in the context, say \"I couldn't find that information.\"\n\n"
				f"### Context:\n{context}\n\n"
				f"### Question:\n{req.query}\n\n"
				"Answer:"
			)

			# 4) Stream model output
			async for delta in get_openai_chat_completion(prompt):
				# Send as SSE data frames
				yield f"data: {json.dumps(delta)}\n\n"

			# Indicate completion
			yield "event: done\ndata: null\n\n"

		except HTTPException:
			raise
		except Exception as e:
			logger.error(f"Chat streaming error: {str(e)}", exc_info=True)
			# Surface the error to the client as an SSE error event
			yield "event: error\n" + f"data: {json.dumps({'message': 'Internal server error'})}\n\n"

	return StreamingResponse(
		event_stream(),
		media_type="text/event-stream",
		headers={
			# Helpful for proxies
			"Cache-Control": "no-cache",
			"Connection": "keep-alive",
		},
	)
