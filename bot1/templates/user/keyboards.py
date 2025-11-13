from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import StatesGroup, State

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def product_reaction_kb():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Готово 👍", callback_data="product_ready")
    keyboard.button(text="Нет 👎", callback_data="product_not_ready")
    keyboard.adjust(2)
    return keyboard.as_markup()