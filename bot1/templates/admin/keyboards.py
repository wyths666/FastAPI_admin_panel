from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def start_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Создание рассылки", callback_data="start_mailing")
    builder.button(text="Редактировать товар", callback_data="redactor")
    builder.adjust(1)
    return builder.as_markup()