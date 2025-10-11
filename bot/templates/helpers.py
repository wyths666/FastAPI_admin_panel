from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

confirm_choice_text = """
Вы уверены?
"""

incorrect_value_text = """
Не верный формат значения!
"""


def confirm_choice_ikb(yes_callback: str, comeback_callback: str) -> InlineKeyboardMarkup:
    """
        ikb with button Yes and Comeback for confirmation of your choice
    :param yes_callback: callback data for yes btn
    :param comeback_callback: callback data for comeback btn
    :return: InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(
            text='✅ Да',
            callback_data=yes_callback
        ),
        InlineKeyboardButton(
            text='⬅️ Назад',
            callback_data=comeback_callback
        )
    )
    builder.adjust(1)
    return builder.as_markup()


def comeback_ikb(callback: str) -> InlineKeyboardMarkup:
    """
        ikb with url on admin
    :param callback: callback data for button
    :return: InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(
            text='⬅️ Назад',
            callback_data=callback
        )
    )
    builder.adjust(1)
    return builder.as_markup()
