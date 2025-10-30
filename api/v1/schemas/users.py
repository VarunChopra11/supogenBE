from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field, EmailStr


class DiscordBotPermissions(BaseModel):
    permissions_value: Optional[int] = Field(None)
    admin: bool = Field(False)
    scopes: Optional[List[str]] = Field(default_factory=list)


class DiscordServer(BaseModel):
    server_id: str
    server_name: str
    joined_at: datetime = Field(default_factory=datetime.now(timezone.utc))
    owner_id: Optional[str] = None
    member_count: Optional[int] = None
    bot_permissions: DiscordBotPermissions = Field(default_factory=DiscordBotPermissions)


class UserModel(BaseModel):
    user_id: str
    name: str
    email: EmailStr
    picture: Optional[str] = None
    servers: Optional[List[DiscordServer]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=datetime.now(timezone.utc))

    class Config:
        orm_mode = True
        validate_assignment = True
        json_schema_extra = {
            "example": {
                "user_id": "123456789012345678",
                "name": "Varun",
                "email": "varun@example.com",
                "picture": "https://cdn.discordapp.com/avatars/123/avatar.png",
                "servers": [
                    {
                        "server_id": "987654321098765432",
                        "server_name": "My Discord Server",
                        "member_count": 120,
                        "bot_permissions": {
                            "permissions_value": 8,
                            "admin": True,
                            "scopes": ["bot", "applications.commands"],
                        },
                    }
                ],
            }
        }


class UserResponse(BaseModel):
    user_id: str
    email: EmailStr
    name: str = None
    picture: Optional[str] = None