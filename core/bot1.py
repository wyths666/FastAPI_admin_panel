from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import cnf, Bot1Config

bot1 = Bot(
    token=cnf.bot1.TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)
bot_config = Bot1Config()
