import secrets
from typing import List, Dict, Any, Union
from datetime import datetime
from decimal import Decimal
from beanie import Document
from typing import get_origin, get_args, Optional
from pydantic import TypeAdapter, ValidationError, Field, ConfigDict
from typing import get_type_hints
from pymongo import IndexModel, ASCENDING, DESCENDING, TEXT


class Users(Document):
    id: int
    username: str
    full_name: Optional[str] = None
    role: str = "user"
    banned: str = "0"

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("id", ASCENDING)], unique=True),
            IndexModel([("username", ASCENDING)]),
            IndexModel([("banned", ASCENDING)])
        ]

class Products(Document):
    id: int
    title: str
    desc: str
    image_id: str

    class Settings:
        name = "products"
        indexes = [
            IndexModel([("id", ASCENDING)], unique=True),
            IndexModel([("title", TEXT)])  # Текстовый поиск
        ]

class Messages(Document):
    from_id: int
    message_object: Optional[str] = ""
    checked: str = "0"
    date: datetime
    file_id: str
    file_type: str = "none"
    from_operator: str = "0"
    id: int


    class Settings:
        name = "messages"
        indexes = [
            # Основной индекс для поиска сообщений пользователя
            IndexModel([("from_id", ASCENDING)]),

            # Для сортировки по дате (новые сначала)
            IndexModel([("date", DESCENDING)]),

            # Составной индекс для частых запросов
            IndexModel([("from_id", ASCENDING), ("date", DESCENDING)]),

            # Для поиска непрочитанных сообщений
            IndexModel([("checked", ASCENDING), ("from_id", ASCENDING)]),

            # Уникальный индекс для id сообщения
            IndexModel([("id", ASCENDING)], unique=True)
        ]