from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from bot.templates.admin import menu as tadmin
from bot.templates.admin.menu import AdminState, quick_messages_ikb, admin_reply_ikb
from bot.templates.user.menu import user_reply_ikb
from config import cnf
from db.beanie.models import Claim, AdminMessage, KonsolPayment
from core.bot import bot, bot_config
from db.beanie.models.models import MOSCOW_TZ, ChatSession, UserMessage
from utils.konsol_client import konsol_client
from utils.pending_storage import pending_actions
router = Router()


async def send_message_to_user(user_id: int, claim_id: str, text: str):
    """Отправляет ТЕКСТОВОЕ сообщение пользователю и сохраняет в историю"""
    message_text = text or "Сообщение без текста"

    # ✅ ДОБАВЛЯЕМ ХЕШТЕГ К СООБЩЕНИЮ
    message_with_hashtag = f"Сообщение по заявке №{claim_id}\n{message_text}"

    # Сохраняем в базу
    await AdminMessage.create(
        claim_id=claim_id,
        from_admin_id=user_id,
        to_user_id=user_id,
        message_text=message_text,
        is_reply=False
    )

    # ОТПРАВЛЯЕМ В ГРУППУ С ХЕШТЕГОМ
    try:
        await bot.send_message(
            chat_id=cnf.bot.GROUP_ID,
            text=f"🛡️ <b>Администратор:</b>\n{message_with_hashtag}",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"⚠️ Не удалось отправить в группу: {e}")

    # Отправляем пользователю (БЕЗ КНОПКИ ОТВЕТА)
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"📨 Сообщение от администратора по заявке {claim_id}:\n\n{message_text}"
            # ✅ УБИРАЕМ reply_markup=user_reply_ikb(claim_id)
        )
        return True
    except Exception as e:
        print(f"Ошибка отправки пользователю {user_id}: {e}")
        return False

@router.callback_query(F.data.startswith("message_"))
async def start_message_to_user(call: CallbackQuery):
    claim_id = call.data.replace("message_", "")

    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        await call.answer("Заявка не найдена", show_alert=True)
        return

    # ✅ СОЗДАЕМ ИЛИ АКТИВИРУЕМ ЧАТ-СЕССИЮ
    session = await ChatSession.find_one(
        ChatSession.claim_id == claim_id,
        ChatSession.is_active == True
    )

    if not session:
        # Создаем новую сессию
        session = await ChatSession(
            claim_id=claim_id,
            user_id=claim.user_id,
            admin_chat_id=None,  # Пока не создаем чат в группе
            is_active=True,
            has_unanswered=False
        ).create()

        # Создаем сообщение-маркер в группе с хештегом
        try:
            marker_message = await bot.send_message(
                chat_id=cnf.bot.GROUP_ID,
                text=f"💬 <b>Чат по заявке #{claim_id}</b>\n"
                     f"<i>Все сообщения с хештегом #{claim_id} будут связаны с этой заявкой</i>",
                parse_mode="HTML"
            )

            # Обновляем сессию с ID чата
            await session.set({ChatSession.admin_chat_id: marker_message.message_id})

        except Exception as e:
            print(f"⚠️ Не удалось создать маркер в группе: {e}")

    # Сохраняем действие
    pending_actions[call.from_user.id] = {
        "type": "message",
        "claim_id": claim_id,
        "user_id": claim.user_id
    }

    # Предлагаем быстрые шаблоны или свой текст
    await call.message.answer(
        f"💬 Отправка сообщения по заявке #{claim_id}\n\n"
        f"Выберите шаблон или введите свой текст:",
        reply_markup=quick_messages_ikb(claim_id)
    )
    await call.answer()


@router.callback_query(F.data.startswith("chat_"))
async def view_chat_history(call: CallbackQuery):
    claim_id = call.data.replace("chat_", "")

    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        await call.answer("Заявка не найдена", show_alert=True)
        return

    messages = await AdminMessage.find(AdminMessage.claim_id == claim_id).sort("created_at").to_list()

    if not messages:
        await call.answer("История сообщений пуста", show_alert=True)
        return

    chat_history = f"📋 История переписки по заявке {claim_id}\n"
    chat_history += f"👤 Пользователь: {claim.user_id}\n\n"

    for msg in messages:
        sender = "👤 Пользователь" if msg.is_reply else "🛡️ Админ"
        chat_history += f"{sender} ({msg.created_at.strftime('%H:%M %d.%m')}):\n{msg.message_text}\n\n"

    await call.message.answer(chat_history)
    await call.answer()


@router.callback_query(F.data.startswith("custom_"))
async def ask_custom_text(call: CallbackQuery):
    claim_id = call.data.replace("custom_", "")

    await call.message.answer(
        f"✍️ Введите ваш текст для заявки {claim_id}:",
        reply_markup=ForceReply(input_field_placeholder="Текст сообщения...")
    )
    await call.answer()


@router.callback_query(F.data.startswith("ask_screenshot_"))
async def send_screenshot_request(call: CallbackQuery):
    claim_id = call.data.replace("ask_screenshot_", "")

    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        await call.answer("Заявка не найдена", show_alert=True)
        return

    message_text = f"Пожалуйста, отправьте скриншот еще раз для проверки качества."

    await send_message_to_user(claim.user_id, claim_id, message_text)
    await call.answer()


@router.callback_query(F.data.startswith("ask_payment_"))
async def send_payment_request(call: CallbackQuery):
    claim_id = call.data.replace("ask_payment_", "")

    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        await call.answer("Заявка не найдена", show_alert=True)
        return

    message_text = (
        f"Пожалуйста, уточните платежные данные для перевода."
    )

    await send_message_to_user(claim.user_id, claim_id, message_text)
    await call.answer()


# @router.message(F.reply_to_message)
# async def handle_force_reply(msg: Message):
#     user_id = msg.from_user.id
#
#
#     if user_id in pending_actions:
#         action = pending_actions[user_id]
#
#
#         if action["type"] == "message":
#             # Админ пишет пользователю
#             await process_admin_to_user_message(msg, action)
#
#         elif action["type"] == "user_reply":
#             # Пользователь отвечает админу
#             await process_user_to_admin_reply(msg, action)
#
#         del pending_actions[user_id]
#
#     else:
#         print(f"🔍 Действие НЕ найдено для user_id: {user_id}")
#         await msg.answer("❌ Сессия устарела. Начните заново.")
#
#
#
# async def process_admin_to_user_message(msg: Message, action: dict):
#     """Обработка сообщения от админа к пользователю"""
#     claim_id = action["claim_id"]
#     target_user_id = action["user_id"]
#
#     # ✅ ПОЛУЧАЕМ СЕССИЮ
#     session = await ChatSession.find_one(
#         ChatSession.claim_id == claim_id,
#         ChatSession.is_active == True
#     )
#
#     # ОБРАБАТЫВАЕМ ФОТО И ТЕКСТ
#     if msg.photo:
#         largest_photo = msg.photo[-1]
#         file_id = largest_photo.file_id
#         caption = msg.caption or "Фото от администратора"
#
#         # ✅ ДОБАВЛЯЕМ ХЕШТЕГ
#         caption_with_hashtag = f"{caption}\n\n#{claim_id}" if caption else f"#{claim_id}"
#
#         # Сохраняем в базу
#         await AdminMessage.create(
#             claim_id=claim_id,
#             from_admin_id=msg.from_user.id,
#             to_user_id=target_user_id,
#             message_text=caption,
#             is_reply=False
#         )
#
#         # ✅ ОТПРАВЛЯЕМ В ГРУППУ С ХЕШТЕГОМ
#         try:
#             await bot.send_photo(
#                 chat_id=cnf.bot.GROUP_ID,
#                 photo=file_id,
#                 caption=f"🛡️ <b>Администратор:</b>\n{caption_with_hashtag}",
#                 parse_mode="HTML"
#             )
#         except Exception as e:
#             print(f"⚠️ Не удалось отправить фото в группу: {e}")
#
#         # Отправляем фото пользователю (без хештега)
#         try:
#             await bot.send_photo(
#                 chat_id=target_user_id,
#                 photo=file_id,
#                 caption=f"📨 Сообщение от администратора по заявке {claim_id}:\n\n{caption}",
#                 reply_markup=user_reply_ikb(claim_id)
#             )
#             await msg.answer("✅ Фото отправлено пользователю")
#         except Exception as e:
#             await msg.answer(f"❌ Ошибка отправки фото: {e}")
#
#     else:
#         message_text = msg.text or msg.caption or "Сообщение от администратора"
#
#         # ✅ ДОБАВЛЯЕМ ХЕШТЕГ
#         message_with_hashtag = f"{message_text}\n\n#{claim_id}"
#
#         await AdminMessage.create(
#             claim_id=claim_id,
#             from_admin_id=msg.from_user.id,
#             to_user_id=target_user_id,
#             message_text=message_text,
#             is_reply=False
#         )
#
#         # ✅ ОТПРАВЛЯЕМ В ГРУППУ С ХЕШТЕГОМ
#         try:
#             await bot.send_message(
#                 chat_id=cnf.bot.GROUP_ID,
#                 text=f"🛡️ <b>Администратор:</b>\n{message_with_hashtag}",
#                 parse_mode="HTML"
#             )
#         except Exception as e:
#             print(f"⚠️ Не удалось отправить в группу: {e}")
#
#         # Отправляем пользователю (без хештега)
#         try:
#             await bot.send_message(
#                 chat_id=target_user_id,
#                 text=f"📨 Сообщение от администратора по заявке {claim_id}:\n\n{message_text}",
#                 reply_markup=user_reply_ikb(claim_id)
#             )
#             await msg.answer("✅ Сообщение отправлено пользователю")
#         except Exception as e:
#             await msg.answer(f"❌ Ошибка отправки: {e}")
#
#
# async def process_user_to_admin_reply(msg: Message, action: dict):
#     """Обработка ответа пользователя админу"""
#     claim_id = action["claim_id"]
#
#     # ✅ ПОЛУЧАЕМ СЕССИЮ
#     session = await ChatSession.find_one(
#         ChatSession.claim_id == claim_id,
#         ChatSession.is_active == True
#     )
#
#     # ОБРАБАТЫВАЕМ ФОТО И ТЕКСТ ОТ ПОЛЬЗОВАТЕЛЯ
#     if msg.photo:
#         largest_photo = msg.photo[-1]
#         file_id = largest_photo.file_id
#         caption = msg.caption or "Фото от пользователя"
#
#         # ✅ ДОБАВЛЯЕМ ХЕШТЕГ
#         caption_with_hashtag = f"{caption}\n\n#{claim_id}" if caption else f"#{claim_id}"
#
#         # Сохраняем в базу
#         await AdminMessage.create(
#             claim_id=claim_id,
#             from_admin_id=msg.from_user.id,
#             to_user_id=msg.from_user.id,
#             message_text=caption,
#             is_reply=True
#         )
#
#         # ✅ ОТПРАВЛЯЕМ В ГРУППУ С ХЕШТЕГОМ
#         try:
#             await bot.send_photo(
#                 chat_id=cnf.bot.GROUP_ID,
#                 photo=file_id,
#                 caption=f"👤 <b>Пользователь:</b>\n{caption_with_hashtag}",
#                 parse_mode="HTML"
#             )
#         except Exception as e:
#             print(f"⚠️ Не удалось отправить фото в группу: {e}")
#
#         # Отправляем фото админам (без хештега)
#         for admin_id in bot_config.ADMINS:
#             try:
#                 await bot.send_photo(
#                     chat_id=admin_id,
#                     photo=file_id,
#                     caption=f"💬 Фото от пользователя по заявке {claim_id}:\n\n{caption}",
#                     reply_markup=admin_reply_ikb(claim_id)
#                 )
#             except Exception as e:
#                 print(f"Ошибка отправки фото админу {admin_id}: {e}")
#
#         await msg.answer("✅ Фото отправлено администратору")
#
#     else:
#         message_text = msg.text or msg.caption or "Сообщение от пользователя"
#
#         # ✅ ДОБАВЛЯЕМ ХЕШТЕГ
#         message_with_hashtag = f"{message_text}\n\n#{claim_id}"
#
#         await AdminMessage.create(
#             claim_id=claim_id,
#             from_admin_id=msg.from_user.id,
#             to_user_id=msg.from_user.id,
#             message_text=message_text,
#             is_reply=True
#         )
#
#         # ✅ ОТПРАВЛЯЕМ В ГРУППУ С ХЕШТЕГОМ
#         try:
#             await bot.send_message(
#                 chat_id=cnf.bot.GROUP_ID,
#                 text=f"👤 <b>Пользователь:</b>\n{message_with_hashtag}",
#                 parse_mode="HTML"
#             )
#         except Exception as e:
#             print(f"⚠️ Не удалось отправить в группу: {e}")
#
#         # Уведомляем админов (без хештега)
#         for admin_id in bot_config.ADMINS:
#             try:
#                 await bot.send_message(
#                     chat_id=admin_id,
#                     text=f"💬 Ответ от пользователя по заявке {claim_id}:\n\n{message_text}",
#                     reply_markup=admin_reply_ikb(claim_id)
#                 )
#             except Exception as e:
#                 print(f"Ошибка уведомления админа {admin_id}: {e}")
#
#         await msg.answer("✅ Ваш ответ отправлен администратору")


@router.message(F.chat.type == "private")
async def handle_all_user_messages(msg: Message):
    """Автоматически обрабатывает ВСЕ сообщения пользователя в личке"""

    # Ищем активную сессию для пользователя
    session = await ChatSession.find_one(
        ChatSession.user_id == msg.from_user.id,
        ChatSession.is_active == True
    )

    if not session:
        # Если нет активной сессии - стандартное поведение
        await msg.answer("У Вас нет активных чатов с администратором.\nЕсли у Вас остались вопросы обратитесь в поддержку /help")
        return

    # Проверяем что заявка еще не обработана
    claim = await Claim.get(claim_id=session.claim_id)
    if claim.claim_status in ["confirm", "cancelled"]:
        await session.set({ChatSession.is_active: False, ChatSession.closed_at: datetime.now()})
        await msg.answer("Ваша заявка обработана, чат с администратором закрыт")
        return

    # ✅ ПРАВИЛЬНО ОПРЕДЕЛЯЕМ ТЕКСТ СООБЩЕНИЯ
    if msg.text:
        message_text = msg.text
    elif msg.photo and msg.caption:
        message_text = msg.caption
    elif msg.photo:
        message_text = "📷 Фото"
    else:
        message_text = "📎 Файл"

    user_message = UserMessage(
        user_id=msg.from_user.id,
        claim_id=session.claim_id,
        text=message_text,  # ✅ Теперь всегда строка
        is_from_user=True,
        has_media=bool(msg.photo),
        photo_file_id=msg.photo[-1].file_id if msg.photo else None
    )
    await user_message.insert()

    # ✅ Помечаем как неотвеченное
    await session.set({ChatSession.has_unanswered: True})

    # ✅ Пересылаем в группу с хештегом
    try:
        if msg.text:
            await bot.send_message(
                chat_id=cnf.bot.GROUP_ID,
                text=f"Сообщение по заявке №{session.claim_id}\n👤 <b>Пользователь:</b>\n{msg.text}",
                parse_mode="HTML"
            )
        elif msg.photo:
            caption_text = msg.caption or "📷 Фото"
            await bot.send_photo(
                chat_id=cnf.bot.GROUP_ID,
                photo=msg.photo[-1].file_id,
                caption=f"Сообщение по заявке №{session.claim_id}\n👤 <b>Пользователь:</b>\n{msg.text}",
                parse_mode="HTML"
            )
    except Exception as e:
        print(f"Ошибка отправки в группу: {e}")

    await msg.answer("✅ Сообщение отправлено администратору")


@router.message(F.chat.id == cnf.bot.GROUP_ID)
async def handle_group_messages(msg: Message):
    """Обрабатывает сообщения из группы (от админов)"""

    # Игнорируем служебные сообщения и команды
    if msg.text and msg.text.startswith('/'):
        return

    # Ищем сессию по хештегу в тексте
    claim_id = None

    if msg.text and '#' in msg.text:
        # Ищем хештег с номером заявки
        import re
        matches = re.findall(r'#(\d+)', msg.text)
        if matches:
            claim_id = matches[0]

    if not claim_id:
        # Если хештега нет, ищем по ID сообщения (если это ответ)
        if msg.reply_to_message:
            replied_text = msg.reply_to_message.text or msg.reply_to_message.caption or ""
            matches = re.findall(r'#(\d+)', replied_text)
            if matches:
                claim_id = matches[0]

    if not claim_id:
        return  # Не нашли заявку

    # Нашли сессию
    session = await ChatSession.find_one(
        ChatSession.claim_id == claim_id,
        ChatSession.is_active == True
    )

    if not session:
        await msg.reply("❌ Не найдена активная сессия для этой заявки")
        return

    # ✅ ПРАВИЛЬНО ОПРЕДЕЛЯЕМ ТЕКСТ ДЛЯ СОХРАНЕНИЯ
    if msg.text:
        message_text = msg.text
    elif msg.photo and msg.caption:
        message_text = msg.caption
    elif msg.photo:
        message_text = "📷 Фото"
    else:
        message_text = "📎 Медиа-файл"

    # ✅ Пересылаем пользователю
    try:
        if msg.text:
            clean_text = msg.text.replace('#' + claim_id, '').strip()
            await bot.send_message(
                chat_id=session.user_id,
                text=f"🛡️ <b>Администратор:</b>\n{clean_text}",
                parse_mode="HTML"
            )
        elif msg.photo:
            caption = msg.caption or ""
            clean_caption = caption.replace('#' + claim_id, '').strip()

            await bot.send_photo(
                chat_id=session.user_id,
                photo=msg.photo[-1].file_id,
                caption=f"🛡️ <b>Администратор:</b>\n{clean_caption}",
                parse_mode="HTML"
            )

        # Сохраняем сообщение
        user_message = UserMessage(
            user_id=session.user_id,
            claim_id=session.claim_id,
            text=message_text,  # ✅ Теперь всегда строка
            is_from_user=False,
            admin_id=msg.from_user.id,
            has_media=bool(msg.photo),
            photo_file_id=msg.photo[-1].file_id if msg.photo else None
        )
        await user_message.insert()

        # ✅ Помечаем как отвеченное
        await session.set({ChatSession.has_unanswered: False})

        await msg.reply("✅ Отправлено пользователю")

    except Exception as e:
        await msg.reply(f"❌ Ошибка: {e}")