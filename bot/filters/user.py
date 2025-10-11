from aiogram.filters import BaseFilter
from aiogram.types import Message

from db.beanie.models import User


class NewUser(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        # Проверяем, есть ли пользователь в MongoDB
        user = await User.check(tg_id=message.from_user.id)
        return not bool(user)