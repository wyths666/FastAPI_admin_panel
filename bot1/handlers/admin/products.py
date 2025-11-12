from aiogram import Router, F
from aiogram.filters import StateFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InputMediaPhoto
from bot1.filters.admin import IsAdmin
from bot1.templates.admin.states import ProductStates
from bot1.templates.admin.keyboards import products_management_kb, products_pagination_kb, product_edit_kb, \
    start_admin_kb
import math

from utils.database import get_database_bot1

router = Router()


# Главное меню управления товарами
@router.callback_query(F.data == "manage_products")
async def manage_products(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "🛍️ <b>Управление товарами</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=products_management_kb()
    )
    await call.answer()


# Добавление нового товара - шаг 1 (название)
@router.callback_query(F.data == "add_new_product")
async def add_new_product_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(ProductStates.waiting_product_name)
    await call.message.edit_text(
        "📝 <b>Добавление нового товара</b>\n\n"
        "Введите название товара:",
        parse_mode="HTML"
    )
    await call.answer()


# Шаг 2 (описание)
@router.message(ProductStates.waiting_product_name)
async def process_product_name(msg: Message, state: FSMContext):
    if len(msg.text) > 100:
        await msg.answer("❌ Название слишком длинное (максимум 100 символов)")
        return

    await state.update_data(title=msg.text)
    await state.set_state(ProductStates.waiting_product_description)
    await msg.answer(
        "📝 Теперь введите описание товара:"
    )


# Шаг 3 (изображение)
@router.message(ProductStates.waiting_product_description)
async def process_product_description(msg: Message, state: FSMContext):
    if len(msg.text) > 1000:
        await msg.answer("❌ Описание слишком длинное (максимум 1000 символов)")
        return

    await state.update_data(desc=msg.text)
    await state.set_state(ProductStates.waiting_product_image)
    await msg.answer(
        "🖼️ Теперь отправьте изображение товара:"
    )


# Финальный шаг - сохранение товара
@router.message(ProductStates.waiting_product_image, F.photo)
async def process_product_image(msg: Message, state: FSMContext):
    data = await state.get_data()

    try:
        db = get_database_bot1()
        products_collection = db["products"]

        # Генерируем новый ID (максимальный существующий + 1)
        last_product = await products_collection.find().sort("id", -1).limit(1).to_list(length=1)
        new_id = (last_product[0]["id"] + 1) if last_product else 1

        # Создаем товар
        product_data = {
            "id": new_id,
            "title": data['title'],
            "desc": data['desc'],
            "image_id": msg.photo[-1].file_id
        }

        await products_collection.insert_one(product_data)

        await msg.answer(
            f"✅ <b>Товар успешно добавлен!</b>\n\n"
            f"<b>ID:</b> {new_id}\n"
            f"<b>Название:</b> {data['title']}\n"
            f"<b>Описание:</b> {data['desc'][:100]}...\n\n"
            f"🔗 <b>Ссылка для пользователей:</b>\n"
            f"https://t.me/вашбот?start={new_id}",
            parse_mode="HTML", reply_markup=products_management_kb()
        )

        await state.clear()

    except Exception as e:
        await msg.answer(f"❌ Ошибка при сохранении товара: {e}")
        await state.clear()


# Если отправлено не изображение
@router.message(ProductStates.waiting_product_image)
async def process_wrong_product_image(msg: Message, state: FSMContext):
    await msg.answer("❌ Пожалуйста, отправьте изображение товара")


# Редактирование существующих товаров - список с пагинацией
@router.callback_query(F.data == "edit_existing_product")
async def edit_existing_products(call: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        db = get_database_bot1()
        products_collection = db["products"]

        # Получаем первую страницу товаров
        products = await products_collection.find().sort("id", 1).limit(12).to_list(length=12)
        total_products = await products_collection.count_documents({})
        total_pages = math.ceil(total_products / 12)

        if not products:
            # Пытаемся отредактировать, если не получается - отправляем новое
            try:
                await call.message.edit_text(
                    "❌ Товары не найдены",
                    reply_markup=products_management_kb()
                )
            except:
                await call.message.answer(
                    "❌ Товары не найдены",
                    reply_markup=products_management_kb()
                )
            return

        # Определяем, можно ли редактировать текущее сообщение
        try:
            # Пытаемся отредактировать существующее сообщение
            await call.message.edit_text(
                f"📦 <b>Выберите товар для редактирования</b>\n\n"
                f"Страница 1/{total_pages}",
                parse_mode="HTML",
                reply_markup=products_pagination_kb(products, 1, total_pages)
            )
        except:
            # Если не получается редактировать, отправляем новое сообщение
            await call.message.answer(
                f"📦 <b>Выберите товар для редактирования</b>\n\n"
                f"Страница 1/{total_pages}",
                parse_mode="HTML",
                reply_markup=products_pagination_kb(products, 1, total_pages)
            )

        await call.answer()
    except Exception as e:
        # Обработка ошибок загрузки товаров
        try:
            await call.message.edit_text(f"❌ Ошибка при загрузке товаров: {e}")
        except Exception as e:
            await call.message.answer(f"❌ Ошибка при загрузке товаров: {e}")


# Пагинация по товарам
@router.callback_query(F.data.startswith("products_page_"))
async def products_pagination(call: CallbackQuery):
    page = int(call.data.split("_")[2])
    skip = (page - 1) * 12

    try:
        db = get_database_bot1()
        products_collection = db["products"]

        products = await products_collection.find().sort("id", 1).skip(skip).limit(12).to_list(length=12)
        total_products = await products_collection.count_documents({})
        total_pages = math.ceil(total_products / 12)


        await call.message.edit_text(
            f"📦 <b>Выберите товар для редактирования</b>\n\n",
            parse_mode="HTML",
            reply_markup=products_pagination_kb(products, page, total_pages)
        )
        await call.answer()
    except Exception as e:
        await call.answer(f"❌ Ошибка: {e}")


# Выбор конкретного товара для редактирования
@router.callback_query(F.data.startswith("edit_product_"))
async def edit_product(call: CallbackQuery, state: FSMContext):
    product_id = int(call.data.split("_")[2])

    try:
        db = get_database_bot1()
        products_collection = db["products"]

        product = await products_collection.find_one({"id": product_id})

        if not product:
            await call.answer("❌ Товар не найден")
            return

        await state.update_data(editing_product_id=product_id)

        # Отправляем фото товара

        await call.message.edit_media(
            media=InputMediaPhoto(
                media=product['image_id'],
                caption=f"🛍️ <b>Товар для редактирования</b>\n\n"
                        f"<b>ID:</b> {product['id']}\n"
                        f"<b>Название:</b> {product['title']}\n"
                        f"<b>Описание:</b> {product['desc'][:200]}...\n\n"
                        f"🔗 <b>Ссылка:</b> https://t.me/вашбот?start={product['id']}",
                parse_mode="HTML"
            ),
            reply_markup=product_edit_kb(product_id)
        )
        await call.answer()
    except Exception as e:
        await call.answer(f"❌ Ошибка: {e}")


# Редактирование названия
@router.callback_query(F.data.startswith("edit_name_"))
async def edit_product_name(call: CallbackQuery, state: FSMContext):
    product_id = int(call.data.split("_")[2])
    await state.update_data(editing_product_id=product_id)
    await state.set_state(ProductStates.waiting_edit_name)

    await call.message.delete()
    await call.message.answer(
        "✏️ Введите новое название товара:"
    )
    await call.answer()


@router.message(ProductStates.waiting_edit_name)
async def process_edit_name(msg: Message, state: FSMContext):
    if len(msg.text) > 100:
        await msg.answer("❌ Название слишком длинное (максимум 100 символов)")
        return

    data = await state.get_data()
    product_id = data['editing_product_id']

    try:
        db = get_database_bot1()
        products_collection = db["products"]

        result = await products_collection.update_one(
            {"id": product_id},
            {"$set": {"title": msg.text}}
        )

        if result.modified_count > 0:
            # Получаем обновленный товар
            product = await products_collection.find_one({"id": product_id})

            # Отправляем фото товара с обновленными данными
            await msg.answer_photo(
                photo=product['image_id'],
                caption=f"🛍️ <b>Товар для редактирования</b>\n\n"
                        f"<b>ID:</b> {product['id']}\n"
                        f"<b>Название:</b> {product['title']}\n"
                        f"<b>Описание:</b> {product['desc'][:200]}...\n\n"
                        f"🔗 <b>Ссылка:</b> https://t.me/вашбот?start={product['id']}",
                parse_mode="HTML",
                reply_markup=product_edit_kb(product_id)
            )

            await msg.answer(f"✅ Название товара обновлено!")
        else:
            await msg.answer("❌ Товар не найден")

    except Exception as e:
        await msg.answer(f"❌ Ошибка при обновлении: {e}")

    await state.clear()


# Редактирование описания
@router.callback_query(F.data.startswith("edit_desc_"))
async def edit_product_desc(call: CallbackQuery, state: FSMContext):
    product_id = int(call.data.split("_")[2])
    await state.update_data(editing_product_id=product_id)
    await state.set_state(ProductStates.waiting_edit_description)

    await call.message.delete()
    await call.message.answer(
        "📝 Введите новое описание товара:"
    )
    await call.answer()


@router.message(ProductStates.waiting_edit_description)
async def process_edit_desc(msg: Message, state: FSMContext):
    if len(msg.text) > 1000:
        await msg.answer("❌ Описание слишком длинное (максимум 1000 символов)")
        return

    data = await state.get_data()
    product_id = data['editing_product_id']

    try:
        db = get_database_bot1()
        products_collection = db["products"]

        result = await products_collection.update_one(
            {"id": product_id},
            {"$set": {"desc": msg.text}}
        )

        if result.modified_count > 0:
            # Получаем обновленный товар
            product = await products_collection.find_one({"id": product_id})

            # Отправляем фото товара с обновленными данными
            await msg.answer_photo(
                photo=product['image_id'],
                caption=f"🛍️ <b>Товар для редактирования</b>\n\n"
                        f"<b>ID:</b> {product['id']}\n"
                        f"<b>Название:</b> {product['title']}\n"
                        f"<b>Описание:</b> {product['desc'][:200]}...\n\n"
                        f"🔗 <b>Ссылка:</b> https://t.me/вашбот?start={product['id']}",
                parse_mode="HTML",
                reply_markup=product_edit_kb(product_id)
            )

            await msg.answer(f"✅ Описание товара обновлено!")
        else:
            await msg.answer("❌ Товар не найден")

    except Exception as e:
        await msg.answer(f"❌ Ошибка при обновлении: {e}")

    await state.clear()


# Редактирование изображения
@router.callback_query(F.data.startswith("edit_image_"))
async def edit_product_image(call: CallbackQuery, state: FSMContext):
    product_id = int(call.data.split("_")[2])
    await state.update_data(editing_product_id=product_id)
    await state.set_state(ProductStates.waiting_edit_image)

    await call.message.delete()
    await call.message.answer(
        "🖼️ Отправьте новое изображение товара:"
    )
    await call.answer()


@router.message(ProductStates.waiting_edit_image, F.photo)
async def process_edit_image(msg: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data['editing_product_id']

    try:
        db = get_database_bot1()
        products_collection = db["products"]

        result = await products_collection.update_one(
            {"id": product_id},
            {"$set": {"image_id": msg.photo[-1].file_id}}
        )

        if result.modified_count > 0:
            # Получаем обновленный товар
            product = await products_collection.find_one({"id": product_id})

            # Отправляем новое фото товара
            await msg.answer_photo(
                photo=msg.photo[-1].file_id,
                caption=f"🛍️ <b>Товар для редактирования</b>\n\n"
                        f"<b>ID:</b> {product['id']}\n"
                        f"<b>Название:</b> {product['title']}\n"
                        f"<b>Описание:</b> {product['desc'][:200]}...\n\n"
                        f"🔗 <b>Ссылка:</b> https://t.me/вашбот?start={product['id']}",
                parse_mode="HTML",
                reply_markup=product_edit_kb(product_id)
            )

            await msg.answer("✅ Изображение товара обновлено!")
        else:
            await msg.answer("❌ Товар не найден")

    except Exception as e:
        await msg.answer(f"❌ Ошибка при обновлении: {e}")

    await state.clear()


# Если отправлено не изображение при редактировании
@router.message(ProductStates.waiting_edit_image)
async def process_wrong_edit_image(msg: Message, state: FSMContext):
    await msg.answer("❌ Пожалуйста, отправьте изображение товара")


# Назад к списку товаров
@router.callback_query(F.data == "back_to_products_list")
async def back_to_products_list(call: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        # Удаляем сообщение с карточкой товара
        await call.message.delete()
    except Exception:
        # Игнорируем ошибки если сообщение уже удалено
        pass

    # Вызываем функцию показа списка товаров
    await edit_existing_products(call, state)


# Назад к управлению товарами
@router.callback_query(F.data == "back_to_products_manage")
async def back_to_products_manage(call: CallbackQuery, state: FSMContext):
    await manage_products(call, state)


@router.callback_query(F.data == "admin_back")
async def admin_back(call: CallbackQuery, state: FSMContext):
    await state.clear()

    await call.message.edit_text(
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=start_admin_kb()
    )
    await call.answer()