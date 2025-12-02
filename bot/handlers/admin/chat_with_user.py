from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from bot.handlers.user.commands import ban_check_middleware
from bot.templates.admin.menu import AdminState, quick_messages_ikb, admin_reply_ikb
from bot.templates.user.menu import user_reply_ikb
from config import cnf
from db.beanie.models import Claim, AdminMessage, KonsolPayment
from core.bot import bot, bot_config
from db.beanie.models.models import ChatSession, UserMessage, ChatMessage, User
from utils.konsol_client import konsol_client
from utils.pending_storage import pending_actions


router = Router()
router.callback_query.middleware(ban_check_middleware)
router.message.middleware(ban_check_middleware)

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
async def handle_all_user_messages(message: Message):
    # user_id = message.from_user.id
    # user = await User.get(tg_id=user_id)
    # if user.banned:
    #     return
    try:
        user_id = message.from_user.id

        # Ищем сессию с САМЫМ ПОСЛЕДНИМ взаимодействием
        chat_session = await ChatSession.find_one(
            {"user_id": user_id, "is_active": True},
            sort=[("last_interaction", -1)]  # самая свежая по взаимодействию
        )

        if not chat_session:
            await message.answer("❌ У вас нет активных чатов с поддержкой.")
            return

        claim_id = chat_session.claim_id

        # Проверяем поддерживаемые типы сообщений
        if not message.text and not message.photo and not message.document:
            await message.answer("❌ Поддерживаются только текстовые сообщения, фото и документы.")
            return

        # Получаем текст сообщения или подпись
        if message.text:
            text = message.text
        elif message.caption:
            text = message.caption
        else:
            text = ""

        # Обрабатываем фото
        photo_file_id = None
        has_photo = False
        if message.photo:
            photo_file_id = message.photo[-1].file_id
            has_photo = True

        # Обрабатываем документы (has_photo=False, но photo_file_id заполнен)
        document_file_id = None
        document_name = None
        document_size = None
        if message.document:
            document_file_id = message.document.file_id
            document_name = message.document.file_name
            document_size = message.document.file_size
            # Для документов используем photo_file_id поле, но has_photo=False
            photo_file_id = document_file_id
            has_photo = False

        # Сохраняем сообщение в chat_messages
        chat_message = ChatMessage(
            session_id=claim_id,
            claim_id=claim_id,
            user_id=user_id,
            message=text,
            is_bot=False,  # сообщение от пользователя
            has_photo=has_photo,
            photo_file_id=photo_file_id,
            photo_caption=text if (has_photo or message.document) else None,
            timestamp=datetime.now()
        )

        await chat_message.insert()

        # Дополнительно сохраняем информацию о документе если это документ
        if message.document:
            # Можно сохранить в отдельное поле или добавить логику для отличия документов от фото
            # Пока используем существующую структуру, но добавляем информацию в message
            if text:
                # Если есть текст, добавляем информацию о документе
                chat_message.message = f"📎 {document_name}\n{text}"
            else:
                chat_message.message = f"📎 {document_name}"
            await chat_message.save()

        # ОБНОВЛЯЕМ время последнего взаимодействия и флаг неотвеченных
        chat_session.last_interaction = datetime.now()
        chat_session.has_unanswered = True
        await chat_session.save()

        print(f"✅ Сообщение пользователя {user_id} сохранено в сессию {claim_id} "
              f"({'текст' if message.text else 'фото' if message.photo else 'документ'})")

        # Уведомляем админов о новом сообщении (если нужно)
        # await notify_admins_about_new_message(chat_session, chat_message)

    except Exception as e:
        print(f"❌ Ошибка сохранения сообщения пользователя: {e}")
        import traceback
        traceback.print_exc()


async def notify_admins_about_new_message(chat_session: ChatSession, chat_message: ChatMessage):
    """Уведомление админов о новом сообщении от пользователя"""
    try:
        # Здесь логика уведомления админов в админ-боте
        # Например, отправка сообщения в админский чат

        if chat_session.admin_chat_id:
            # Отправляем уведомление конкретному админу
            admin_message = f"📩 Новое сообщение в чате {chat_session.claim_id}:\n\n{chat_message.message}"

            if chat_message.has_photo:
                # Отправляем фото с подписью
                await bot.send_photo(
                    chat_id=chat_session.admin_chat_id,
                    photo=chat_message.photo_file_id,
                    caption=admin_message
                )
            else:
                # Отправляем текстовое сообщение
                await bot.send_message(
                    chat_id=chat_session.admin_chat_id,
                    text=admin_message
                )

        print(f"✅ Админ уведомлен о новом сообщении в сессии {chat_session.claim_id}")

    except Exception as e:
        print(f"❌ Ошибка уведомления админа: {e}")


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