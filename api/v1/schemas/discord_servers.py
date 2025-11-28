from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class DiscordBotPermissions(BaseModel):
    permissions_value: Optional[int] = Field(None)
    is_authenticated: bool = Field(False)
    admin: bool = Field(False)

class Forums(BaseModel):
    forum_id: str
    forum_name: str
    
class DiscordServer(BaseModel):
    user_id: str
    server_id: str
    server_name: str
    owner_username: Optional[str] = None
    member_count: Optional[int] = None
    forums: Optional[list[Forums]] = None
    selected_forums: Optional[list[Forums]] = None
    bot_permissions: DiscordBotPermissions = Field(default_factory=DiscordBotPermissions)
    joined_at: datetime = Field(default_factory=datetime.now(timezone.utc))


class DiscordServerData(BaseModel):
    server_id: str
    server_name: str
    owner_id: Optional[str] = None
    owner_username: Optional[str] = None
    member_count: Optional[int] = None
    forums: Optional[list[Forums]] = None
    selected_forums: Optional[list[Forums]] = None
    bot_permissions: DiscordBotPermissions = Field(default_factory=DiscordBotPermissions)
    joined_at: datetime = Field(default_factory=datetime.now(timezone.utc))


class UpdateSelectedForumsRequest(BaseModel):
    server_id: str
    selected_forums: list[Forums]
