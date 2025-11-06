from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ResponseBase(BaseModel):
    success: bool

class ClaimResponse(BaseModel):
    claim_id: str
    user_id: int
    code: str
    claim_status: str
    process_status: str
    payment_method: str
    phone: str | None
    card: str | None
    review_text: str
    photo_count: int
    created_at: datetime

class ChatMessageSchema(BaseModel):
    id: str
    claim_id: str
    user_id: int
    message: str
    is_bot: bool
    has_photo: bool = False
    photo_file_id: Optional[str] = None
    photo_caption: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True