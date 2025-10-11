from datetime import datetime

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ForceReply
from bot.templates.admin import menu as tadmin
from bot.templates.admin.menu import AdminState, quick_messages_ikb, admin_reply_ikb
from bot.templates.user.menu import user_reply_ikb
from db.beanie.models import Claim, AdminMessage
from core.bot import bot, bot_config

router = Router()

pending_actions = {}  # {user_id: {"type": "message", "claim_id": "000001", "data": {...}}}
pending_replies = {}  # Для ForceReply

@router.callback_query(tadmin.ClaimCallback.filter())
async def handle_claim_action(call: CallbackQuery, callback_data: tadmin.ClaimCallback):
    claim_id = callback_data.claim_id
    action = callback_data.action

    # === Находим заявку в MongoDB ===
    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        await call.answer("Заявка не найдена в базе.", show_alert=True)
        return

    # === Определяем статусы ===
    if action == "accept":
        claim_status = "confirm"
        process_status = "complete"
        status_text = "Принята"
        # Имитация оплаты
        await fake_payment_api(claim_id)
    else:  # "reject"
        claim_status = "cancelled"
        process_status = "cancelled"
        status_text = "Отклонена"

    # === Обновляем заявку в MongoDB ===
    await claim.update(
        claim_status=claim_status,
        process_status=process_status
    )

    # === Обновляем сообщение в группе ===
    new_text = f"{call.message.text}\n\nСтатус: {status_text}"
    await call.message.edit_text(text=new_text)

    await call.answer()


async def fake_payment_api(claim_id: str):
    """Заглушка вместо реального API Konsol.pro"""
    print(f"[PAYMENT] Имитация оплаты по заявке {claim_id}")
    # TODO: в будущем — вызов integrations/konsol.py


@router.callback_query(F.data.startswith("message_"))
async def start_message_to_user(call: CallbackQuery):
    claim_id = call.data.replace("message_", "")

    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        await call.answer("Заявка не найдена", show_alert=True)
        return

    # Сохраняем действие
    pending_actions[call.from_user.id] = {
        "type": "message",
        "claim_id": claim_id,
        "user_id": claim.user_id
    }

    # Предлагаем быстрые шаблоны или свой текст
    await call.message.answer(
        f"💬 Отправка сообщения по заявке {claim_id}\n\n"
        f"Выберите шаблон или введите свой текст:",
        reply_markup=quick_messages_ikb(claim_id)
    )
    await call.answer()


async def send_message_to_user(user_id: int, claim_id: str, text: str):
    """Отправляет ТЕКСТОВОЕ сообщение пользователю и сохраняет в историю"""
    message_text = text or "Сообщение без текста"

    # Сохраняем в базу
    await AdminMessage.create(
        claim_id=claim_id,
        from_admin_id=user_id,  # В реальности это ID того, кто вызывает функцию
        to_user_id=user_id,
        message_text=message_text,
        is_reply=False
    )

    # Отправляем пользователю
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"📨 Сообщение от администратора по заявке {claim_id}:\n\n{message_text}",
            reply_markup=user_reply_ikb(claim_id)
        )
        return True
    except Exception as e:
        print(f"Ошибка отправки пользователю {user_id}: {e}")
        return False


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
    await call.message.answer("✅ Запрос на скриншот отправлен")
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
    await call.message.answer("✅ Запрос на уточнение платежных данных отправлен")
    await call.answer()


@router.message(F.reply_to_message)
async def handle_force_reply(msg: Message):
    user_id = msg.from_user.id

    if user_id in pending_actions:
        action = pending_actions[user_id]

        if action["type"] == "message":
            # Админ пишет пользователю
            await process_admin_to_user_message(msg, action)

        elif action["type"] == "user_reply":
            # Пользователь отвечает админу
            await process_user_to_admin_reply(msg, action)

        del pending_actions[user_id]


async def process_admin_to_user_message(msg: Message, action: dict):
    """Обработка сообщения от админа к пользователю"""
    claim_id = action["claim_id"]
    target_user_id = action["user_id"]

    # ✅ ОБРАБАТЫВАЕМ ФОТО И ТЕКСТ
    if msg.photo:
        # Если отправлено фото
        largest_photo = msg.photo[-1]
        file_id = largest_photo.file_id
        caption = msg.caption or "Фото от администратора"

        # Сохраняем в базу
        await AdminMessage.create(
            claim_id=claim_id,
            from_admin_id=msg.from_user.id,
            to_user_id=target_user_id,
            message_text=caption,
            is_reply=False
        )

        # Отправляем фото пользователю
        try:
            await bot.send_photo(
                chat_id=target_user_id,
                photo=file_id,
                caption=f"📨 Сообщение от администратора по заявке {claim_id}:\n\n{caption}",
                reply_markup=user_reply_ikb(claim_id)
            )
            await msg.answer("✅ Фото отправлено пользователю")
        except Exception as e:
            await msg.answer(f"❌ Ошибка отправки фото: {e}")

    else:
        # Если отправлен текст
        message_text = msg.text or msg.caption or "Сообщение от администратора"

        await AdminMessage.create(
            claim_id=claim_id,
            from_admin_id=msg.from_user.id,
            to_user_id=target_user_id,
            message_text=message_text,
            is_reply=False
        )

        try:
            await bot.send_message(
                chat_id=target_user_id,
                text=f"📨 Сообщение от администратора по заявке {claim_id}:\n\n{message_text}",
                reply_markup=user_reply_ikb(claim_id)
            )
            await msg.answer("✅ Сообщение отправлено пользователю")
        except Exception as e:
            await msg.answer(f"❌ Ошибка отправки: {e}")


async def process_user_to_admin_reply(msg: Message, action: dict):
    """Обработка ответа пользователя админу"""
    claim_id = action["claim_id"]

    # ✅ ОБРАБАТЫВАЕМ ФОТО И ТЕКСТ ОТ ПОЛЬЗОВАТЕЛЯ
    if msg.photo:
        # Если пользователь отправил фото
        largest_photo = msg.photo[-1]
        file_id = largest_photo.file_id
        caption = msg.caption or "Фото от пользователя"

        # Сохраняем в базу
        await AdminMessage.create(
            claim_id=claim_id,
            from_admin_id=msg.from_user.id,
            to_user_id=msg.from_user.id,
            message_text=caption,
            is_reply=True
        )

        # Отправляем фото всем админам
        for admin_id in bot_config.ADMINS:
            try:
                await bot.send_photo(
                    chat_id=admin_id,
                    photo=file_id,
                    caption=f"💬 Фото от пользователя по заявке {claim_id}:\n\n{caption}",
                    reply_markup=admin_reply_ikb(claim_id)
                )
            except Exception as e:
                print(f"Ошибка отправки фото админу {admin_id}: {e}")

        await msg.answer("✅ Фото отправлено администратору")

    else:
        # Если пользователь отправил текст
        message_text = msg.text or msg.caption or "Сообщение от пользователя"

        await AdminMessage.create(
            claim_id=claim_id,
            from_admin_id=msg.from_user.id,
            to_user_id=msg.from_user.id,
            message_text=message_text,
            is_reply=True
        )

        # Уведомляем админов
        for admin_id in bot_config.ADMINS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"💬 Ответ от пользователя по заявке {claim_id}:\n\n{message_text}",
                    reply_markup=admin_reply_ikb(claim_id)
                )
            except Exception as e:
                print(f"Ошибка уведомления админа {admin_id}: {e}")

        await msg.answer("✅ Ваш ответ отправлен администратору")