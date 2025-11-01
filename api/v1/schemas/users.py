from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field, EmailStr

class UserModel(BaseModel):
    user_id: str
    name: str
    email: EmailStr
    picture: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UserResponse(BaseModel):
    user_id: str
    email: EmailStr
    name: str = None
    picture: Optional[str] = None