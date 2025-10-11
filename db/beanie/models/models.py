from typing import Optional, Union
from beanie import Document
from datetime import datetime
import pytz

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

    async def update(self, **kwargs):
        """
        Обновляет поля объекта новыми значениями.
        """
        _set = {"$set": {}}

        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise self.CellTypeExp(f"В модели `{self.__class__.__name__}` отсутствует поле `{key}`")
            elif not isinstance(self.__dict__.get(key), type(value)):
                raise self.CellTypeExp(
                    f"Тип данных поля `{key}` модели `{self.__class__.__name__}` является {type(self.__dict__.get(key))} (не {type(value)})")
            _set["$set"][key] = value

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
    created_at: datetime = datetime.now(MOSCOW_TZ)

    class Settings:
        name = "users"

class Claim(ModelAdmin):
    claim_id: str                   # "000001"
    user_id: int                    # tg_id
    code: str
    code_status: str                # "valid" / "invalid"
    process_status: str             # "process" / "complete" / "cancelled"
    claim_status: str               # "confirm" / "cancelled"
    payment_method: str             # "phone" / "card"
    phone: Optional[str] = None
    card: Optional[str] = None
    bank: Optional[str] = None
    review_text: str = ""
    photo_file_ids: list[str] = []
    created_at: datetime = datetime.now(MOSCOW_TZ)
    updated_at: datetime = datetime.now(MOSCOW_TZ)

    class Settings:
        name = "claims"

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

