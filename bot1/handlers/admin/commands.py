import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import StateFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ForceReply
from core.logger import bot_1_logger as logger
from bot1.filters.admin import IsAdmin
from bot1.templates.admin.keyboards import start_admin_kb
from bot1.templates.admin.states import AdminMailingState
from core.bot1 import bot1
from db.beanie_bot1.models import Users

router = Router()

@router.message(Command("admin"), IsAdmin())
async def start_admin(msg: Message, state: FSMContext):
    await state.clear()

    await msg.answer("Выберите действие:", reply_markup=start_admin_kb())


@router.callback_query(F.data.startswith("start_mailing"))
async def start_mailing(call: CallbackQuery, state: FSMContext):
    await state.clear()

    await state.set_state(AdminMailingState.waiting_message_to_mailing)

    await call.message.reply(
        text="<b>Введите сообщение для рассылки:</b>",
        parse_mode="HTML"
        )
    await call.answer()


@router.message(AdminMailingState.waiting_message_to_mailing)
async def process_mailing_message(msg: Message, state: FSMContext):
    await state.clear()

    # Получаем всех пользователей из базы данных
    try:
        users = await Users.find_all().to_list()
    except Exception as e:
        logger.error(f"Ошибка при получении пользователей из БД: {e}")
        await msg.answer("❌ Ошибка при получении списка пользователей")
        return

    # Фильтруем пользователей (исключаем забаненных, если нужно)
    active_users = [user for user in users if not user.banned]

    if not active_users:
        await msg.answer("❌ Нет активных пользователей для рассылки")
        return

    sent_count = 0
    failed_count = 0

    # Отправляем сообщение о начале рассылки
    progress_msg = await msg.answer(f"📤 Начинаю рассылку... 0/{len(active_users)}")

    # Рассылка сообщения всем пользователям
    for user in active_users:
        try:
            # Проверяем тип сообщения и отправляем соответствующим образом
            if msg.text:
                await msg.bot.send_message(
                    chat_id=user.tg_id,
                    text=msg.text,
                    parse_mode=msg.parse_mode if msg.parse_mode else None
                )
            elif msg.photo:
                await msg.bot.send_photo(
                    chat_id=user.tg_id,
                    photo=msg.photo[-1].file_id,
                    caption=msg.caption,
                    parse_mode=msg.parse_mode if msg.parse_mode else None
                )
            elif msg.video:
                await msg.bot.send_video(
                    chat_id=user.tg_id,
                    video=msg.video.file_id,
                    caption=msg.caption,
                    parse_mode=msg.parse_mode if msg.parse_mode else None
                )
            elif msg.document:
                await msg.bot.send_document(
                    chat_id=user.tg_id,
                    document=msg.document.file_id,
                    caption=msg.caption,
                    parse_mode=msg.parse_mode if msg.parse_mode else None
                )
            else:
                # Если тип сообщения не поддерживается, отправляем текст
                if msg.caption:
                    await msg.bot.send_message(
                        chat_id=user.tg_id,
                        text=msg.caption,
                        parse_mode=msg.parse_mode if msg.parse_mode else None
                    )
                else:
                    failed_count += 1
                    continue

            sent_count += 1

            # Обновляем прогресс каждые 10 отправленных сообщений
            if sent_count % 10 == 0:
                await progress_msg.edit_text(
                    f"📤 Рассылка... {sent_count}/{len(active_users)}"
                )

            # Небольшая задержка чтобы не превысить лимиты Telegram
            await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Ошибка при отправке пользователю {user.tg_id}: {e}")
            failed_count += 1
            continue

    # Финальное сообщение с результатами
    result_text = (
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Всего пользователей: {len(active_users)}\n"
        f"• Успешно отправлено: {sent_count}\n"
        f"• Не удалось отправить: {failed_count}\n"
        f"• Процент успеха: {(sent_count / len(active_users)) * 100:.1f}%"
    )

    await progress_msg.edit_text(result_text, parse_mode="HTML")