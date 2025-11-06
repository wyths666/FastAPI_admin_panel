import asyncio
import contextlib

from aiogram import Dispatcher, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommandScopeDefault, BotCommandScopeChat

from bot.handlers import routers
from config import cnf
from core.bot import bot
from core.logger import bot_logger as logger

from db.beanie.models import document_models
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from db.mysql.crud import init_mysql
from utils.database import init_database

dp = Dispatcher(
    bot=bot,
    storage=MemoryStorage()
)
dp.include_routers(*routers)



async def startup(bot: Bot) -> None:
    """
    Активируется при запуске бота
    """
    # === Инициализация MongoDB (Beanie) ===
    await init_database()
    # mongo_client = AsyncIOMotorClient(cnf.mongo.URL)
    # await init_beanie(
    #     database=mongo_client[cnf.mongo.NAME],
    #     document_models=document_models
    # )
    logger.info("✅ MongoDB (Beanie) подключена")

    # === Инициализация MySQL ===
    await init_mysql()
    logger.info("✅ MySQL подключена")


    # === Настройка команд бота ===
    await bot.delete_webhook()
    user_commands = [
        cmd for cmd in cnf.bot.COMMANDS
        if cmd.command != "admin"
    ]
    await bot.set_my_commands(
        commands=user_commands,
        scope=BotCommandScopeDefault()
    )
    # for admin in cnf.bot.ADMINS or []:
    #     with contextlib.suppress(TelegramBadRequest):
    #         await bot.set_my_commands(
    #             cnf.bot.COMMANDS + cnf.bot.ADMIN_COMMANDS,
    #             scope=BotCommandScopeChat(chat_id=admin)
    #         )

    logger.info('=== Bot started ===')


async def shutdown(bot: Bot) -> None:
    """
    Активируется при выключении
    """
    await bot.close()
    await dp.stop_polling()
    logger.info('=== Bot stopped ===')


async def main() -> None:
    dp.startup.register(startup)
    dp.shutdown.register(shutdown)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Exit')