from datetime import datetime
from pydantic import BaseModel
from typing import Optional, Dict, Any
from bson import ObjectId



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

class CloseChatRequest(BaseModel):
    claim_id: str


class SupportSessionResponse(BaseModel):
    id: str
    user_id: int
    state: Optional[str]
    state_data: Dict[str, Any]
    created_at: datetime
    resolved: bool
    resolved_by_admin_id: Optional[int]
    previous_state: Optional[str]
    previous_state_data: Optional[dict]
    rollback_count: Optional[int]
    username: Optional[str] = None
    first_name: Optional[str] = None

class SupportMessageResponse(BaseModel):
    id: str
    session_id: str
    user_id: int
    message: str
    is_bot: bool
    has_photo: bool
    photo_file_id: Optional[str]
    photo_caption: Optional[str]
    has_document: bool
    document_file_id: Optional[str]
    document_name: Optional[str]
    document_mime_type: Optional[str]
    document_size: Optional[int]
    timestamp: datetime

class SendMessageRequest(BaseModel):
    message: str
    has_photo: bool = False
    photo_file_id: Optional[str] = None
    photo_caption: Optional[str] = None
    has_document: bool = False
    document_file_id: Optional[str] = None
    document_name: Optional[str] = None
    document_mime_type: Optional[str] = None

class RollbackRequest(BaseModel):
    steps: int = 1