from datetime import datetime, timezone
from pydantic import BaseModel, Field

class DocumentModel(BaseModel):
    document_id: str
    user_id: str
    server_id: str
    document_url: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


