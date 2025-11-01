from pydantic import BaseModel, HttpUrl
from typing import List, Optional
from uuid import UUID
from bson import ObjectId


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")


class ChunkBase(BaseModel):
    chunk_id: UUID
    doc_url: str
    heading: str
    anchor: str
    level: int
    chunk_index: int
    text: str
    tokens: int
    embedding: Optional[List[float]] = None


class ChunkCreate(ChunkBase):
    user_id: UUID
    server_id: UUID


class MarkdownProcessRequest(BaseModel):
    server_id: str
    document_url: HttpUrl 
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "server_id": "123e4567-e89b-12d3-a456-426614174000",
                "document_url": "https://example.com/docs/api.md"
            }
        }
    }


class MarkdownProcessResponse(BaseModel):
    success: bool
    message: str
    chunks_created: int
