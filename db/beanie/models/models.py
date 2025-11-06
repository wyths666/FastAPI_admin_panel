import hashlib
import secrets

import pytz
from typing import List, Dict, Any, Union
from datetime import datetime
from decimal import Decimal
from beanie import Document
from typing import get_origin, get_args, Optional
from pydantic import TypeAdapter, ValidationError, Field, ConfigDict
from typing import get_type_hints
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Базовый класс для CRUD-операций
class ModelAdmin(Document):
    class CellTypeExp(Exception):
        pass

    @classmethod
    async def create(cls, data: dict = None, **kwargs): # type: ignore
        """
        Создает новый объект и вставляет его в базу данных.
        """
        if data: 
            kwargs = data
        obj = cls(**kwargs)

        await obj.insert()
        return obj

    class CellTypeExp(Exception):
        """Кастомное исключение для ошибок типов."""
        pass

    async def update(self, **kwargs):
        """
        Обновляет поля объекта новыми значениями с проверкой типов через Pydantic.
        """
        _set = {"$set": {}}

        # Получаем аннотации типов класса
        annotations = get_type_hints(self.__class__)

        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise self.CellTypeExp(f"В модели `{self.__class__.__name__}` отсутствует поле `{key}`")

            # Получаем аннотацию поля
            field_annotation = annotations.get(key)
            if not field_annotation:
                # Если аннотация отсутствует, пропускаем проверку
                _set["$set"][key] = value
                continue

            # === Проверка типа через Pydantic ===
            try:
                adapter = TypeAdapter(field_annotation)
                # Проверяем значение
                adapter.validate_python(value)
            except ValidationError as e:
                raise self.CellTypeExp(
                    f"Недопустимый тип или значение для поля `{key}` модели `{self.__class__.__name__}`: "
                    f"{e.errors()[0]['msg']}"
                ) from e

            # === Если проверка прошла — добавляем в обновление ===
            _set["$set"][key] = value

        # === Выполняем обновление в БД ===
        await super().update(_set)

    async def delete(self):
        """
        Удаляет объект из базы данных.
        """
        await super().delete()

    @classmethod
    async def get(cls, **kwargs):
        """
        Возвращает один объект, соответствующий критериям поиска.
        """
        return await cls.find_one(kwargs)

    @classmethod
    async def check(cls, **kwargs) -> Optional[str]:
        """
        Проверяет наличие объекта, соответствующего критериям поиска, и возвращает его ID.
        """
        obj = await cls.find_one(kwargs)
        return str(obj.id) if obj else None

    @classmethod
    async def filter(cls, **kwargs):
        """
        Возвращает список объектов, соответствующих критериям поиска.
        """
        return await cls.find(kwargs).to_list()

    @classmethod
    async def all(cls):
        """
        Возвращает список всех объектов.
        """
        return await cls.find_all().to_list()


class AdminMessage(ModelAdmin):
    claim_id: str
    from_admin_id: int
    to_user_id: int
    message_text: str = ""
    is_reply: bool = False
    created_at: datetime = datetime.now(MOSCOW_TZ)

    class Settings:
        name = "admin_messages"


class User(ModelAdmin):
    tg_id: int
    username: Optional[str] = None
    role: str = "user"
    banned: bool = False
    # === Поля для Konsol API ===
    kind: str = "individual"  # всегда "individual"
    created_at: datetime = datetime.now(MOSCOW_TZ)

    class Settings:
        name = "users"


class Claim(ModelAdmin):
    contractor_id: Optional[str] = None
    claim_id: str  # "000001"
    user_id: int  # tg_id
    code: str
    code_status: str  # "valid" / "invalid"
    process_status: str = "process"  # "process" / "complete" / "cancelled"
    claim_status: str = "pending"  # "pending", "confirm", "cancelled"
    payment_method: str  # "phone" / "card"
    amount: float = 100.00  # Сумма платежа

    # === Реквизиты из заявки (не дублируются в User) ===
    phone: Optional[str] = None  # если выбрана СБП
    card: Optional[str] = None  # если выбрана карта
    bank_member_id: Optional[str] = None  # если выбрана СБП

    review_text: str = ""
    photo_file_ids: List[str] = []

    # === Связь с платежом ===
    konsol_payment_id: Optional[str] = None  # ID в коллекции konsol_payments

    created_at: datetime = datetime.now(MOSCOW_TZ)
    updated_at: datetime = datetime.now(MOSCOW_TZ)

    class Settings:
        name = "claims"
        use_state_management = True

    def update_status(self, claim_status: str, process_status: str):
        """Метод для обновления статусов"""
        self.claim_status = claim_status
        self.process_status = process_status
        self.updated_at = datetime.now(MOSCOW_TZ)

    @classmethod
    async def generate_next_claim_id(cls) -> str:
        """
        Генерирует следующий номер заявки в формате 000001, 000002, ...
        """
        last_claim = await cls.find_all().sort("-claim_id").limit(1).to_list()
        if last_claim:
            last_num = int(last_claim[0].claim_id)
            return f"{last_num + 1:06d}"
        return "000001"


class KonsolPayment(ModelAdmin):
    """Модель для платежей konsol.pro"""
    konsol_id: Optional[str] = None  # ID платежа в konsol.pro (заполняется после создания)
    contractor_id: str  # ID исполнителя в Konsol (берётся из User)
    amount: Decimal = Decimal("100.00")  # Сумма (Decimal)
    status: str  # created, manualpay, executed, failed, nalog_unbound
    purpose: str  # Назначение платежа
    services_list: List[Dict[str, Any]]  # Список услуг: [{"title": "...", "amount": "100.00"}]
    bank_details_kind: str  # "fps", "card", "bank_account"

    # === Реквизиты (только одно заполнено в зависимости от bank_details_kind) ===
    card_number: Optional[str] = None  # Для kind="card"
    phone_number: Optional[str] = None  # Для kind="fps"
    bank_member_id: Optional[str] = None  # Для kind="fps" — ID банка из справочника

    # === Связь с заявкой и пользователем ===
    claim_id: Optional[str] = None  # ID заявки (из Claim)
    user_id: Optional[int] = None  # tg_id пользователя (для удобства поиска)

    # === Временные метки ===
    created_at: datetime = datetime.now(MOSCOW_TZ)
    updated_at: datetime = datetime.now(MOSCOW_TZ)
    paid_at: Optional[datetime] = None  # Заполняется при статусе "executed"

    class Settings:
        name = "konsol_payments"
        indexes = [
            "konsol_id",
            "user_id",
            "status",
            "contractor_id",
            "claim_id",
            "bank_details_kind",
            "phone_number",
            "card_number"
        ]

class ChatSession(Document):
    claim_id: str
    user_id: int
    admin_chat_id: Optional[int] = None
    is_active: bool = True
    has_unanswered: bool = False
    created_at: datetime = datetime.now(MOSCOW_TZ)
    closed_at: Optional[datetime] = None

    # ✅ ТОЛЬКО ЭТО
    model_config = ConfigDict(arbitrary_types_allowed=True)

    class Settings:
        name = "chat_sessions"

class UserMessage(Document):
    user_id: int
    claim_id: str
    text: str
    is_from_user: bool
    has_media: bool = False
    photo_file_id: Optional[str] = None
    admin_id: Optional[int] = None
    created_at: datetime = datetime.now(MOSCOW_TZ)

    class Settings:
        name = "user_messages"


class Administrators(ModelAdmin):
    admin_id: int = Field(..., description="ID администратора в Telegram")
    login: str = Field(..., description="Логин для входа")
    password: str = Field(..., description="Пароль (в открытом виде)")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    session_token: Optional[str] = None
    last_login: Optional[datetime] = None

    class Settings:
        name = "administrators"

    def verify_password(self, password: str) -> bool:
        """Проверка пароля - сравниваем как есть"""
        return self.password == password

    @classmethod
    def generate_session_token(cls) -> str:
        return secrets.token_urlsafe(32)


class ChatMessage(Document):
    session_id: str
    claim_id: str
    user_id: int
    message: str
    is_bot: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(MOSCOW_TZ))

    class Settings:
        name = "chat_messages"



