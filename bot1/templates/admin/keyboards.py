from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import StatesGroup, State

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def start_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Создание рассылки", callback_data="start_mailing")
    builder.button(text="Редактировать товар", callback_data="manage_products")
    builder.adjust(1)
    return builder.as_markup()


def products_management_kb():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="➕ Добавить новый товар", callback_data="add_new_product")
    keyboard.button(text="✏️ Редактировать существующий товар", callback_data="edit_existing_product")
    keyboard.button(text="⬅️ Назад", callback_data="admin_back")
    keyboard.adjust(1)
    return keyboard.as_markup()


from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def products_pagination_kb(products: list, page: int, total_pages: int) -> InlineKeyboardMarkup:
    # Создаем отдельные билдеры для каждой секции
    products_builder = InlineKeyboardBuilder()
    pagination_builder = InlineKeyboardBuilder()
    back_builder = InlineKeyboardBuilder()

    # 1. Товары: по одному на строку
    for product in products:
        title = product['title'][:30].strip() or "Без названия"
        products_builder.button(
            text=f"{title}",
            callback_data=f"edit_product_{product['id']}"
        )
    products_builder.adjust(1)  # Каждый товар на отдельной строке

    # 2. Пагинация: одна строка
    if page > 1:
        pagination_builder.button(
            text="◀️",
            callback_data=f"products_page_{page - 1}"
        )

    pagination_builder.button(
        text=f"{page}/{total_pages}",
        callback_data="current_page"
    )

    if page < total_pages:
        pagination_builder.button(
            text="▶️",
            callback_data=f"products_page_{page + 1}"
        )

    pagination_builder.adjust(3)  # Все кнопки пагинации в один ряд

    # 3. Кнопка "Назад"
    back_builder.button(
        text="⬅️ Назад в меню",
        callback_data="back_to_products_manage"
    )
    back_builder.adjust(1)  # Кнопка "Назад" на отдельной строке

    # Объединяем все билдеры
    final_builder = InlineKeyboardBuilder()
    final_builder.attach(products_builder)
    final_builder.attach(pagination_builder)
    final_builder.attach(back_builder)

    return final_builder.as_markup()


def product_edit_kb(product_id: int):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✏️ Изменить название", callback_data=f"edit_name_{product_id}")
    keyboard.button(text="📝 Изменить описание", callback_data=f"edit_desc_{product_id}")
    keyboard.button(text="🖼️ Изменить изображение", callback_data=f"edit_image_{product_id}")
    keyboard.button(text="⬅️ Назад к списку", callback_data="back_to_products_list")
    keyboard.adjust(1)
    return keyboard.as_markup()