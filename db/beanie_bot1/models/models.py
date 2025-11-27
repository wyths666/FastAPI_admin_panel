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
    date: datetime = Field(default_factory=lambda: datetime.now())
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

            # # Уникальный индекс для id сообщения
            # IndexModel([("id", ASCENDING)], unique=True)
        ]


class KonsolPayment(Document):
    """Модель для платежей konsol.pro"""
    konsol_id: Optional[str] = None
    contractor_id: str
    amount: Decimal = Decimal("100.00")
    status: str = "created"
    purpose: str = "Выплата"
    services_list: List[Dict[str, Any]] = [{"title": "Выплата", "amount": "100.00"}]
    bank_details_kind: str  # "fps", "card"

    # Реквизиты
    card_number: Optional[str] = None
    phone_number: Optional[str] = None
    bank_member_id: Optional[str] = None

    # Дополнительные поля для ручного ввода
    first_name: Optional[str] = None  # Имя получателя
    last_name: Optional[str] = None  # Фамилия получателя

    # Временные метки
    created_at: datetime
    updated_at: datetime
    paid_at: Optional[datetime] = None

    class Settings:
        name = "konsol_payments"
        indexes = [
            "konsol_id", "status", "bank_details_kind", "phone_number", "card_number"
        ]