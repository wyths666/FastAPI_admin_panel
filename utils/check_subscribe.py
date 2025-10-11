from aiogram import Bot
from aiogram.types import ChatMember


async def check_user_subscription(bot: Bot, user_id: int, channel_username: str) -> bool:
    """
    Проверяет, подписан ли пользователь на канал.

    :param bot: экземпляр бота
    :param user_id: ID пользователя
    :param channel_username: имя канала (например, "@pure_health")
    :return: True если подписан, иначе False
    """
    try:
        member: ChatMember = await bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False