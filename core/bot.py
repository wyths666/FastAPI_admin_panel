from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import cnf, BotConfig

bot = Bot(
    token=cnf.bot.TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)
bot_config = BotConfig()
