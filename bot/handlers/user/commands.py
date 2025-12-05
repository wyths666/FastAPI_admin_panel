import datetime
import re
from asyncio import Lock
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton

from bot.templates.user.reg import SupportState
from utils.pending_storage import pending_actions
from bot.templates.admin import menu as tadmin
from bot.templates.user import reg as treg
from bot.templates.user import menu as tmenu
from core.bot import bot, bot_config
from db.beanie.models import User, Claim, AdminMessage, SupportSession, SupportMessage
from db.mysql.crud import get_and_delete_code
from utils.check_subscribe import check_user_subscription
from config import cnf
from aiogram.types import FSInputFile

router = Router()
user_locks = {}

async def ban_check_middleware(handler, event, data):
    if hasattr(event, 'from_user') and event.from_user:
        user = await User.get(tg_id=event.from_user.id)
        if user and user.banned:
            # Просто отвечаем на колбэк без уведомления
            if isinstance(event, CallbackQuery):
                await event.answer()
            return
    return await handler(event, data)
router.callback_query.middleware(ban_check_middleware)
router.message.middleware(ban_check_middleware)

@router.message(Command("start"))
async def start_new_user(msg: Message, state: FSMContext):
    await state.clear()

    user_id = msg.from_user.id
    username = msg.from_user.username

    # === Находим или создаём пользователя ===
    user = await User.get(tg_id=user_id)
    if not user:
        # === Создаём нового пользователя ===
        role = "admin" if user_id in bot_config.ADMINS else "user"
        user = await User.create(
            tg_id=user_id,
            username=username,
            role=role
        )
    if user.banned:
        return

    # welcome_photo = FSInputFile("utils/IMG_1262.png")
    welcome_video = FSInputFile("utils/IMG_0017.mp4")
    welcome_text = "👋 Привет! Это бот компании Pure. Введите секретный код, указанный на голограмме."

    await msg.answer_video(
        video=welcome_video,
        caption=welcome_text
    )
    await state.set_state(treg.RegState.waiting_for_code)
    await msg.delete()


@router.message(Command("help"))
async def help_save_state(msg: Message, state: FSMContext):
    user_id = msg.from_user.id
    # user = await User.get(tg_id=user_id)
    # if user and user.banned:
    #     return

    # Ищем последнюю **активную** сессию
    active_session = await SupportSession.find(
    SupportSession.user_id == user_id,
    SupportSession.resolved == False
).sort(-SupportSession.created_at).first_or_none()

    if active_session:
        # ✅ Сессия уже открыта — не создаём новую
        current_state = await state.get_state()
        current_data = await state.get_data() if current_state else {}

        # Обновляем данные FSM (на случай, если пользователь продвинулся дальше)
        await state.update_data(
            original_state=current_state,
            original_data=current_data
        )
        await state.set_state(SupportState.waiting_for_message)

        await msg.answer(
            "🆘 <b>Техническая поддержка</b>\n\n"
            "Ваше обращение уже в работе, Вы можете отправить новое сообщение.\n\n"
            "Для того что-бы отменить обращение и вернуться к оформлению заявки — нажмите кнопку ниже.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ Вернуться к заявке", callback_data="support:back_to_claim")
            ]])
        )
        return

    # ❌ Активной сессии нет — создаём новую
    current_state = await state.get_state()
    current_data = await state.get_data() if current_state else {}

    new_session = await SupportSession(
        user_id=user_id,
        state=current_state,
        state_data=current_data
    ).insert()

    await state.update_data(
        original_state=current_state,
        original_data=current_data
    )
    await state.set_state(SupportState.waiting_for_message)

    await msg.answer(
        "🆘 <b>Техническая поддержка</b>\n\n"
        "Опишите вашу проблему — мы постараемся помочь.\n\n"
        "Если хотите вернуться к оформлению заявки — нажмите кнопку ниже.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="↩️ Вернуться к заявке", callback_data="support:back_to_claim")
        ]])
    )

@router.callback_query(F.data == "send_help_text")
async def help_save(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    # user = await User.get(tg_id=user_id)
    # if user and user.banned:
    #     return

    await callback.answer()

    active_session = await SupportSession.find(
        SupportSession.user_id == user_id,
        SupportSession.resolved == False
    ).sort(-SupportSession.created_at).first_or_none()

    if active_session:
        current_state = await state.get_state()
        current_data = await state.get_data() if current_state else {}

        await state.update_data(
            original_state=current_state,
            original_data=current_data
        )
        await state.set_state(SupportState.waiting_for_message)

        await callback.message.edit_text(
            "🆘 <b>Техническая поддержка</b>\n\n"
            "Ваше обращение уже в работе, Вы можете отправить новое сообщение.\n\n"
            "Для того чтобы отменить обращение и вернуться к оформлению заявки — нажмите кнопку ниже.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ Вернуться к заявке", callback_data="support:back_to_claim")
            ]])
        )
        return

    current_state = await state.get_state()
    current_data = await state.get_data() if current_state else {}

    new_session = await SupportSession(
        user_id=user_id,
        state=current_state,
        state_data=current_data
    ).insert()

    await state.update_data(
        original_state=current_state,
        original_data=current_data
    )
    await state.set_state(SupportState.waiting_for_message)

    await callback.message.edit_text(
        "🆘 <b>Техническая поддержка</b>\n\n"
        "Опишите вашу проблему — мы постараемся помочь.\n\n"
        "Если хотите вернуться к оформлению заявки — нажмите кнопку ниже.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="↩️ Вернуться к заявке", callback_data="support:back_to_claim")
        ]])
    )

@router.message(StateFilter(treg.RegState.waiting_for_code))
async def process_code(msg: Message, state: FSMContext):
    # user_id = msg.from_user.id
    # user = await User.get(tg_id=user_id)
    # if user and user.banned:
    #     return
    if not msg.text:
        await msg.answer(
            "❌ Пожалуйста, отправьте корректный код."
        )
        return

    code = msg.text.strip()

    code_valid = await get_and_delete_code(code)
    if not code_valid and not code == "test":
        await msg.answer_video(video=FSInputFile("utils/IMG_0018.mp4"), caption=treg.code_not_found_text, reply_markup=tmenu.support_ikb())
        return

    await msg.answer_video(video=FSInputFile("utils/IMG_0016.mp4"), caption=treg.code_found_text)

    CHANNEL_USERNAME = cnf.bot.CHANNEL_USERNAME
    is_subscribed = await check_user_subscription(bot, msg.from_user.id, CHANNEL_USERNAME)

    if not is_subscribed:
        await msg.answer_video(video=FSInputFile("utils/IMG_1848.mp4"), caption=treg.not_subscribed_text, reply_markup=tmenu.check_subscription_ikb())
        await state.update_data(entered_code=code)
        return

    await proceed_to_review(user_tg_id=msg.from_user.id, state=state, code=code)


@router.callback_query(treg.RegCallback.filter(F.step == "check_sub"))
async def check_subscription_callback(call: CallbackQuery, state: FSMContext):

    data = await state.get_data()
    code = data.get("entered_code")

    if not code:
        await call.answer("Сессия устарела. Пожалуйста, введите код снова.", show_alert=True)
        await call.message.delete()
        return

    CHANNEL_USERNAME = cnf.bot.CHANNEL_USERNAME
    is_subscribed = await check_user_subscription(bot, call.from_user.id, CHANNEL_USERNAME)

    if not is_subscribed:
        await call.answer("Вы всё ещё не подписаны. Попробуйте снова.", show_alert=True)
        return

    await call.message.delete()
    await proceed_to_review(user_tg_id=call.from_user.id, state=state, code=code)
    await call.answer()


async def proceed_to_review(user_tg_id: int, state: FSMContext, code: str):
    """Переход к отзыву после успешной проверки кода и подписки"""
    claim_id = await Claim.generate_next_claim_id()

    # Создаём заявку с user_tg_id (гарантированно правильный ID)
    await Claim.create(
        claim_id=claim_id,
        user_id=user_tg_id,
        code=code,
        code_status="valid",
        process_status="process",
        claim_status="not_completed",
        payment_method="unknown",
        review_text="",
        photo_file_ids=[]
    )

    await state.update_data(claim_id=claim_id, entered_code=code)
    # Получаем chat_id для отправки сообщения (в личке = user_tg_id)
    await bot.send_message(
        chat_id=user_tg_id,
        text=treg.review_request_text,
        reply_markup=tmenu.send_screenshot_ikb()
    )
    await state.set_state(treg.RegState.waiting_for_screenshot)



@router.callback_query(treg.RegCallback.filter())
async def handle_reg_callback(call: CallbackQuery, callback_data: treg.RegCallback, state: FSMContext):
    step = callback_data.step

    if step == "send_screenshot":
        await call.message.edit_text(text=treg.screenshot_request_text)
        await state.set_state(treg.RegState.waiting_for_screenshot)

    elif step == "phone":
        await call.message.edit_text(text=treg.phone_format_text)
        await state.set_state(treg.RegState.waiting_for_phone_number)

    elif step == "card":
        await call.message.delete()
        await call.message.send_video(video=FSInputFile("utils/IMG_1850.mp4"), caption=treg.card_format_text)
        await state.set_state(treg.RegState.waiting_for_card_number)

    await call.answer()


@router.message(StateFilter(treg.RegState.waiting_for_screenshot))
async def process_screenshot(msg: Message, state: FSMContext):
    if not msg.photo:
        await msg.answer(text=treg.screenshot_error_text, reply_markup=tmenu.support_ikb())
        return

    user_id = msg.from_user.id
    if user_id not in user_locks:
        user_locks[user_id] = Lock()

    async with user_locks[user_id]:
        data = await state.get_data()
        largest_photo = msg.photo[-1]
        file_id = largest_photo.file_id

        current_photos = data.get("photo_file_ids", [])
        current_photos.append(file_id)

        # Сохраняем данные
        await state.update_data(
            photo_file_ids=current_photos,
            review_text=data.get("review_text", "") or msg.caption or "",
            screenshot_received=True
        )

        existing_msg_id = data.get("phone_card_message_id")

        new_text = f"{treg.phone_or_card_text}"

        if existing_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=msg.chat.id,
                    message_id=existing_msg_id,
                    text=new_text,
                    reply_markup=tmenu.phone_or_card_ikb()
                )
            except Exception as e:
                if "message is not modified" not in str(e):
                    print(f"Ошибка редактирования: {e}")
        else:
            sent_msg = await msg.answer(
                text=new_text,
                reply_markup=tmenu.phone_or_card_ikb()
            )
            await state.update_data(phone_card_message_id=sent_msg.message_id)

        await state.set_state(treg.RegState.waiting_for_phone_or_card)


@router.message(StateFilter(treg.RegState.waiting_for_phone_number))
async def process_phone(msg: Message, state: FSMContext):
    # ПРОВЕРЯЕМ, что сообщение содержит текст
    if not msg.text:
        await msg.answer("Не похоже на номер телефона. Пожалуйста, укажите номер телефона в формате +7**********")
        return

    phone = msg.text.strip()

    # ПРОВЕРЯЕМ формат номера телефона
    if not re.match(r'^(?:\+7|8)\d{10}$', phone):
        await msg.answer(
            "Не похоже на номер телефона. Пожалуйста, укажите номер телефона в формате +7**********")
        return

    await state.update_data(phone=phone)
    await msg.answer(text=treg.bank_request_text)
    await state.set_state(treg.RegState.waiting_for_bank)


@router.message(StateFilter(treg.RegState.waiting_for_card_number))
async def process_card(msg: Message, state: FSMContext):
    # ПРОВЕРЯЕМ, что сообщение содержит текст
    if not msg.text:
        await msg.answer("Не похоже на номер карты. Пожалуйста, укажите номер карты в формате 2222 2222 2222 2222")
        return

    card = msg.text.replace(" ", "").strip()

    # ПРОВЕРЯЕМ формат номера карты
    if not card.isdigit() or len(card) != 16:
        await msg.answer(
            "Не похоже на номер карты. Пожалуйста, укажите номер карты в формате 2222 2222 2222 2222")
        return

    await state.update_data(card=card)
    await finalize_claim(user_tg_id=msg.from_user.id, state=state)


@router.message(StateFilter(treg.RegState.waiting_for_bank))
async def process_bank(msg: Message, state: FSMContext):
    # ПРОВЕРЯЕМ, что сообщение содержит текст
    if not msg.text:
        await msg.answer("❌ Пожалуйста, отправьте название банка текстом.")
        return

    bank = msg.text.strip()
    await state.update_data(bank=bank)
    await finalize_claim(user_tg_id=msg.from_user.id, state=state)


async def finalize_claim(user_tg_id: int, state: FSMContext):
    """Завершает заявку и отправляет её в группу менеджеров"""
    data = await state.get_data()
    claim_id = data.get("claim_id")

    if not claim_id:
        await bot.send_message(chat_id=user_tg_id, text="Ошибка: заявка не найдена.")
        return

    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        await bot.send_message(chat_id=user_tg_id, text="Ошибка: заявка не найдена в базе.")
        return

    phone = data.get('phone')
    card = data.get('card')
    bank = data.get('bank', '')
    review_text = data.get('review_text', '—')
    photo_ids = data.get("photo_file_ids", [])

    # === Формируем текст заявки ===
    if phone:
        payment_info = f"Номер телефона: {phone}"
        bank_info = f"Банк: {bank}\n" if bank else ""
        payment_method_label = "phone"
    else:
        payment_info = f"Номер карты: {card}"
        bank_info = ""
        payment_method_label = "card"

    # user_claims = await Claim.filter(user_id=user_tg_id)
    # claim_ids = [claim.claim_id for claim in user_claims if claim.claim_id != claim_id]
    # user_claims_ids = ', '.join(claim_ids) if claim_ids else "Не найдены"
    #
    # claim_text = (
    #     f"Номер заявки: {claim_id}\n"
    #     f"Текст: {review_text}\n"
    #     f"Предыдущие заявки пользователя: {user_claims_ids}\n"
    #     f"{bank_info}"
    #     f"{payment_info}\n"
    #     f"Статус заявки: Не обработано"
    # )

    # # === Отправка в группу ===
    # MANAGER_GROUP_ID = cnf.bot.GROUP_ID
    #
    # # === Определяем клавиатуру ===
    # if phone:  # Если СБП - показываем кнопку для ввода ID банка
    #     keyboard = tadmin.claim_action_ikb_with_bank_button(claim_id)
    # else:  # Если карта - обычная клавиатура
    #     keyboard = tadmin.claim_action_ikb(claim_id)
    #
    # # === Отправка фото и текста ===
    # if photo_ids:
    #     if len(photo_ids) == 1:
    #         # ОДНО ФОТО: отправляем фото с подписью и кнопками
    #         await bot.send_photo(
    #             chat_id=MANAGER_GROUP_ID,
    #             photo=photo_ids[0],
    #             caption=f"{claim_text}",
    #             reply_markup=keyboard  # Используем правильную клавиатуру
    #         )
    #     else:
    #         # НЕСКОЛЬКО ФОТО: создаем медиагруппу
    #         media_group = []
    #         for i, fid in enumerate(photo_ids):
    #             if i == 0:  # Только у первого фото может быть подпись
    #                 media_group.append(types.InputMediaPhoto(
    #                     media=fid,
    #                     caption=f"{claim_text}"
    #                 ))
    #             else:
    #                 media_group.append(types.InputMediaPhoto(media=fid))
    #
    #         try:
    #             await bot.send_media_group(chat_id=MANAGER_GROUP_ID, media=media_group)
    #             # Отправляем кнопки отдельно после медиагруппы
    #             await bot.send_message(
    #                 chat_id=MANAGER_GROUP_ID,
    #                 text=f"Действия по заявке №{claim_id}:",
    #                 reply_markup=keyboard  # Используем правильную клавиатуру
    #             )
    #         except Exception as e:
    #             print(f"Ошибка отправки медиагруппы: {e}")
    #             # Fallback: отправляем по одному
    #             for i, fid in enumerate(photo_ids):
    #                 caption = f"{claim_text}\n\n📸 Скриншот {i + 1}/{len(photo_ids)}" if i == 0 else None
    #                 await bot.send_photo(
    #                     chat_id=MANAGER_GROUP_ID,
    #                     photo=fid,
    #                     caption=caption
    #                 )
    #             await bot.send_message(
    #                 chat_id=MANAGER_GROUP_ID,
    #                 text=f"Действия по заявке №{claim_id}:",
    #                 reply_markup=keyboard  # Используем правильную клавиатуру
    #             )
    # else:
    #     await bot.send_message(
    #         chat_id=MANAGER_GROUP_ID,
    #         text=claim_text,
    #         reply_markup=keyboard  # Используем правильную клавиатуру
    #     )

    # === Подготавливаем данные для обновления ===
    update_data = {
        "process_status": "complete",
        "claim_status": "process",
        "payment_method": payment_method_label,
        "review_text": review_text,
        "photo_file_ids": photo_ids
    }

    # Добавляем данные в зависимости от выбранного способа оплаты
    if phone:  # Если выбран телефон
        update_data["phone"] = phone
        update_data["bank"] = bank
        update_data["card"] = None
    elif card:  # Если выбрана карта
        update_data["card"] = card
        update_data["phone"] = None
        update_data["bank"] = bank
    # === Обновляем заявку ===
    await claim.update(**update_data)

    # === Завершение ===
    await bot.send_video(chat_id=user_tg_id, video=FSInputFile("utils/IMG_0014.mp4"), caption=treg.success_text)
    await state.clear()

@router.message(StateFilter(SupportState.waiting_for_message))
async def handle_support_message(msg: Message, state: FSMContext):
    user_id = msg.from_user.id

    # Находим последнюю активную сессию пользователя
    session = await SupportSession.find(
        SupportSession.user_id == user_id,
        SupportSession.resolved == False
    ).sort(-SupportSession.created_at).first_or_none()

    if not session:
        # fallback: создаём новую сессию на лету
        session = await SupportSession(
            user_id=user_id,
            state=await state.get_state(),
            state_data=await state.get_data()
        ).insert()

    # Определяем тип содержимого
    text = msg.text or msg.caption or ""
    has_photo = bool(msg.photo)
    has_document = bool(msg.document)

    # Неподдерживаемые типы
    if not (text or has_photo or has_document):
        await msg.answer(
            "📎 Отправить можно только:\n"
            "• Текст\n"
            "• Фото (в сжатом виде)\n"
            "• Документ (PDF, DOCX и т.п.)\n\n"
            "Пожалуйста, попробуйте ещё раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="↩️ Вернуться к заявке", callback_data="support:back_to_claim")
            ]])
        )
        return

    # Создаём запись
    support_msg = SupportMessage(
        session_id=session.id,
        user_id=user_id,
        message=text,
        is_bot=False
    )

    # Фото
    if has_photo:
        largest = msg.photo[-1]
        support_msg.has_photo = True
        support_msg.photo_file_id = largest.file_id
        support_msg.photo_caption = msg.caption or ""

    # Документ
    elif has_document:
        doc = msg.document
        # Ограничим размер (например, до 20 МБ)
        if doc.file_size > 20 * 1024 * 1024:
            await msg.answer(
                "⚠️ Файл слишком большой (макс. 20 МБ). Пожалуйста, отправьте уменьшенную версию.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="↩️ Вернуться к заявке", callback_data="support:back_to_claim")
                ]])
            )
            return

        support_msg.has_document = True
        support_msg.document_file_id = doc.file_id
        support_msg.document_name = doc.file_name or "безымянный"
        support_msg.document_mime_type = doc.mime_type or "application/octet-stream"
        support_msg.document_size = doc.file_size

    await support_msg.insert()

    confirmation = "📩 Сообщение отправлено в поддержку."

    if has_photo:
        confirmation += "\n📸 Фото получено."
    elif has_document:
        name = support_msg.document_name
        size_mb = round(support_msg.document_size / (1024 * 1024), 1)
        confirmation += f"\n📄 Документ «{name}» ({size_mb} МБ) получен."

    await msg.answer(
        f"{confirmation}\n\nМы ответим в ближайшее время.\n"
        "Вы по-прежнему можете вернуться к оформлению заявки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="↩️ Вернуться к заявке", callback_data="support:back_to_claim")
        ]])
    )

@router.callback_query(F.data == "support:back_to_claim")
async def back_to_claim_callback(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    data = await state.get_data()

    original_state = data.get("original_state")
    original_data = data.get("original_data", {})

    if not original_state:
        await state.clear()
        try:
            await call.message.edit_text("❌ Незавершенная заявка не найдена. Начните заново: /start")
        except Exception:
            await call.message.answer("❌ Незавершенная не найдена. Начните заново: /start")
        await call.answer()
        return

    # === 1. Находим и закрываем последнюю активную сессию ===
    session = await SupportSession.find(
        SupportSession.user_id == user_id,
        SupportSession.resolved == False
    ).sort(-SupportSession.created_at).first_or_none()

    if session:
        await session.set({"resolved": True, "resolved_by_admin_id": -1})

    # === 2. Восстанавливаем FSM-контекст ===
    await state.set_state(original_state)
    await state.set_data(original_data)

    # === 3. Определяем, какое сообщение показать пользователю ===
    try:
        # 🟢 Состояние: ожидание кода
        if original_state == treg.RegState.waiting_for_code.state:
            code = original_data.get("entered_code")
            if code:
                # → уже ввёл код → проверяем подписку
                CHANNEL_USERNAME = cnf.bot.CHANNEL_USERNAME
                is_subscribed = await check_user_subscription(bot, user_id, CHANNEL_USERNAME)

                if is_subscribed:
                    # Подписан → переходим к отзыву
                    await proceed_to_review(user_tg_id=user_id, state=state, code=code)
                    await call.message.delete()
                    await call.answer()
                    return
                else:
                    # Не подписан → просим подписаться
                    await call.message.delete()
                    await call.message.send_video(video=FSInputFile("utils/IMG_1848.mp4"), caption=treg.not_subscribed_text, reply_markup=tmenu.check_subscription_ikb())
                    await call.answer()
                    return
            else:
                # Ещё не вводил код → приветствие
                welcome_photo = FSInputFile("utils/IMG_1262.png")
                await call.message.delete()
                await call.message.answer_photo(
                    photo=welcome_photo,
                    caption="👋 Привет! Это бот компании Pure. Введите секретный код, указанный на голограмме."
                )
                await call.answer()
                return

        # 🟢 Состояние: ожидание скриншота
        elif original_state == treg.RegState.waiting_for_screenshot.state:
            await call.message.edit_text(
                text=treg.screenshot_request_text,
                reply_markup=None
            )
            await call.answer()
            return

        # 🟢 Состояние: выбор способа получения (телефон / карта)
        elif original_state == treg.RegState.waiting_for_phone_or_card.state:
            await call.message.edit_text(
                text=treg.phone_or_card_text,
                reply_markup=tmenu.phone_or_card_ikb()
            )
            await call.answer()
            return

        # 🟢 Состояние: ввод телефона
        elif original_state == treg.RegState.waiting_for_phone_number.state:
            await call.message.edit_text(text=treg.phone_format_text)
            await call.answer()
            return

        # 🟢 Состояние: ввод карты
        elif original_state == treg.RegState.waiting_for_card_number.state:
            await call.message.delete()
            await call.message.send_video(video=FSInputFile("utils/IMG_1850.mp4"), caption=treg.card_format_text)
            await call.answer()
            return

        # 🟢 Состояние: ввод банка
        elif original_state == treg.RegState.waiting_for_bank.state:
            await call.message.edit_text(text=treg.bank_request_text)
            await call.answer()
            return

        # ❗ Неизвестное состояние — fallback
        else:
            await call.message.edit_text("🔄 Неизвестная ошибка.\nОбратитесь в поддержку.")
            await call.answer()
            return

    except Exception as e:
        import traceback
        print(f"[ERROR] back_to_claim_callback failed: {e}")
        traceback.print_exc()
        try:
            await call.message.edit_text("⚠️ Ошибка при восстановлении сессии. Попробуйте /start")
        except:
            await call.message.answer("⚠️ Ошибка при восстановлении сессии. Попробуйте /start")
        await state.clear()
        await call.answer()