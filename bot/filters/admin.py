from aiogram.filters import BaseFilter
from aiogram.types import Message

from config import cnf


class IsAdmin(BaseFilter):
    async def __call__(self, msg: Message) -> bool:
        """
            Check user in db
        :param msg: Message
        :return: bool
        """
        return msg.from_user.id in cnf.bot.ADMINS
