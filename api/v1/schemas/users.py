from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime



class UserCreate(BaseModel):
    email: EmailStr
    user_id: str = Field(..., min_length=5)
    name: Optional[str] = None
    picture: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: datetime

class UserResponse(BaseModel):
    user_id: str
    email: EmailStr
    name: Optional[str] = None
    picture: Optional[str] = None