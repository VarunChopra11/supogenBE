from typing import List, Literal, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sources: Optional[List[str]] = Field(default=None, description="Source URLs used to generate assistant responses")


class PlaygroundChat(BaseModel):
    chat_id: str
    user_id: str
    server_id: str
    messages: List[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DiscordChat(BaseModel):
    chat_id: str
    user_id: str
    server_id: str
    # Optional Discord specific metadata (channel/thread, etc.)
    channel_id: Optional[str] = None
    thread_id: Optional[str] = None
    messages: List[ChatMessage] = Field(default_factory=list)
    is_resolved: bool = Field(default=False, description="Whether the query has been resolved")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
