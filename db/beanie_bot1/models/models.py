import secrets
from typing import List, Dict, Any, Union
from datetime import datetime
from decimal import Decimal
from beanie import Document
from typing import get_origin, get_args, Optional
from pydantic import TypeAdapter, ValidationError, Field, ConfigDict
from typing import get_type_hints


class User(Document):
    tg_id: int
    username: Optional[str] = None
    role: str = "user"
    banned: bool = False

    class Settings:
        name = "users"


class ChatSession(Document):
    user_id: int
    admin_chat_id: Optional[int] = None
    is_active: bool = True
    has_unanswered: bool = False
    created_at: datetime = Field(default_factory=datetime.now)
    last_interaction: datetime = Field(default_factory=datetime.now)  # ← новое поле
    closed_at: Optional[datetime] = None

    class Settings:
        name = "chat_sessions"


class ChatMessage(Document):
    session_id: str
    claim_id: str
    user_id: int
    message: str = ""  # делаем по умолчанию пустую строку
    is_bot: bool = False
    has_photo: bool = False
    photo_file_id: Optional[str] = None
    photo_caption: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)

    class Settings:
        name = "chat_messages"
        use_state_management = True

    @classmethod
    async def create(cls, **kwargs):
        obj = cls(**kwargs)
        await obj.insert()
        return obj


class Product(Document):
    product_id: int
    title: str
    description: str
    image_id: str
    image_path: str

    class Settings:
        name = "products"

