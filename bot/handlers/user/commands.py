from datetime import datetime
import re
from asyncio import Lock
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from bot.templates.user.reg import SupportState
from bot.templates.user import reg as treg
from bot.templates.user import menu as tmenu
from core.bot import bot, bot_config
from db.beanie.models import User, Claim, AdminMessage, SupportSession, SupportMessage, ChatMessage, ChatSession
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

        await msg.answer(
            "🆘 <b>Техническая поддержка</b>\n\n"
            "Ваше обращение уже в работе, Вы можете отправить новое сообщение.\n\n", parse_mode="HTML")
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

    await msg.answer(
        "🆘 <b>Техническая поддержка</b>\n\n"
        "Опишите вашу проблему — мы постараемся помочь.\n\n"
        ,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "send_help_text")
async def help_save(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
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

        if callback.message and callback.message.text:
            try:
                await callback.message.edit_text(
                    "🆘 <b>Техническая поддержка</b>\n\n"
                    "Ваше обращение уже в работе, Вы можете отправить новое сообщение.\n\n", parse_mode="HTML")
            except Exception as e:
                await callback.message.answer(
                    "🆘 <b>Техническая поддержка</b>\n\n"
                    "Ваше обращение уже в работе, Вы можете отправить новое сообщение.\n\n", parse_mode="HTML")
        else:
            await callback.message.answer(
                "🆘 <b>Техническая поддержка</b>\n\n"
                "Ваше обращение уже в работе, Вы можете отправить новое сообщение.\n\n", parse_mode="HTML")
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

    if callback.message and callback.message.text:
        try:
            await callback.message.edit_text(
                "🆘 <b>Техническая поддержка</b>\n\n"
                "Опишите вашу проблему — мы постараемся помочь.\n\n", parse_mode="HTML")
        except Exception as e:
            await callback.message.answer(
                "🆘 <b>Техническая поддержка</b>\n\n"
                "Опишите вашу проблему — мы постараемся помочь.\n\n", parse_mode="HTML")
    else:
        await callback.message.answer(
            "🆘 <b>Техническая поддержка</b>\n\n"
            "Опишите вашу проблему — мы постараемся помочь.\n\n", parse_mode="HTML")

@router.message(StateFilter(treg.RegState.waiting_for_code))
async def process_code(msg: Message, state: FSMContext):
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
    if not msg.text:
        await msg.answer("Не похоже на номер телефона. Пожалуйста, укажите номер телефона в формате +7**********")
        return

    phone = msg.text.strip()

    if not re.match(r'^(?:\+7|8)\d{10}$', phone):
        await msg.answer(
            "Не похоже на номер телефона. Пожалуйста, укажите номер телефона в формате +7**********")
        return

    await state.update_data(phone=phone)
    await msg.answer(text=treg.bank_request_text)
    await state.set_state(treg.RegState.waiting_for_bank)


@router.message(StateFilter(treg.RegState.waiting_for_card_number))
async def process_card(msg: Message, state: FSMContext):
    if not msg.text:
        await msg.answer("Не похоже на номер карты. Пожалуйста, укажите номер карты в формате 2222 2222 2222 2222")
        return

    card = msg.text.replace(" ", "").strip()

    if not card.isdigit() or len(card) != 16:
        await msg.answer(
            "Не похоже на номер карты. Пожалуйста, укажите номер карты в формате 2222 2222 2222 2222")
        return

    await state.update_data(card=card)
    await finalize_claim(user_tg_id=msg.from_user.id, state=state)


@router.message(StateFilter(treg.RegState.waiting_for_bank))
async def process_bank(msg: Message, state: FSMContext):
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

    if phone:
        payment_info = f"Номер телефона: {phone}"
        bank_info = f"Банк: {bank}\n" if bank else ""
        payment_method_label = "phone"
    else:
        payment_info = f"Номер карты: {card}"
        bank_info = ""
        payment_method_label = "card"


    update_data = {
        "process_status": "complete",
        "claim_status": "process",
        "payment_method": payment_method_label,
        "review_text": review_text,
        "photo_file_ids": photo_ids
    }

    if phone:
        update_data["phone"] = phone
        update_data["bank"] = bank
        update_data["card"] = None
    elif card:
        update_data["card"] = card
        update_data["phone"] = None
        update_data["bank"] = bank
    await claim.update(**update_data)

    await bot.send_video(chat_id=user_tg_id, video=FSInputFile("utils/IMG_0014.mp4"), caption=treg.success_text)
    await state.clear()

@router.message(StateFilter(SupportState.waiting_for_message))
async def handle_support_message(msg: Message, state: FSMContext):
    user_id = msg.from_user.id

    session = await SupportSession.find(
        SupportSession.user_id == user_id,
        SupportSession.resolved == False
    ).sort(-SupportSession.created_at).first_or_none()

    if not session:
        session = await SupportSession(
            user_id=user_id,
            state=await state.get_state(),
            state_data=await state.get_data()
        ).insert()

    text = msg.text or msg.caption or ""
    has_photo = bool(msg.photo)
    has_document = bool(msg.document)

    if not (text or has_photo or has_document):
        await msg.answer(
            "📎 Отправить можно только:\n"
            "• Текст\n"
            "• Фото (в сжатом виде)\n"
            "• Документ (PDF, DOCX и т.п.)\n\n"
            "Пожалуйста, попробуйте ещё раз."
        )
        return

    support_msg = SupportMessage(
        session_id=session.id,
        user_id=user_id,
        message=text,
        is_bot=False
    )

    if has_photo:
        largest = msg.photo[-1]
        support_msg.has_photo = True
        support_msg.photo_file_id = largest.file_id
        support_msg.photo_caption = msg.caption or ""

    elif has_document:
        doc = msg.document
        if doc.file_size > 20 * 1024 * 1024:
            await msg.answer(
                "⚠️ Файл слишком большой (макс. 20 МБ). Пожалуйста, отправьте уменьшенную версию."
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
        f"{confirmation}\n\nМы ответим в ближайшее время."

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
                    await call.message.edit_text(
                        text=treg.not_subscribed_text,
                        reply_markup=tmenu.check_subscription_ikb()
                    )
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

        claim_id = chat_session.claim_id

        # Проверяем поддерживаемые типы сообщений
        if not message.text and not message.photo and not message.document:
            await message.answer("❌ Поддерживаются только текстовые сообщения, фото и документы.")
            return

        # 🟢 Состояние: ввод карты
        elif original_state == treg.RegState.waiting_for_card_number.state:
            await call.message.edit_text(text=treg.card_format_text)
            await call.answer()
            return

        # 🟢 Состояние: ввод банка
        elif original_state == treg.RegState.waiting_for_bank.state:
            await call.message.edit_text(text=treg.bank_request_text)
            await call.answer()
            return

        # ❗ Неизвестное состояние — fallback
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
            is_bot=False,
            has_photo=has_photo,
            photo_file_id=photo_file_id,
            photo_caption=text if (has_photo or message.document) else None,
            timestamp=datetime.now()
        )

        await chat_message.insert()

        if message.document:
            if text:
                chat_message.message = f"📎 {document_name}\n{text}"
            else:
                chat_message.message = f"📎 {document_name}"
            await chat_message.save()

        chat_session.last_interaction = datetime.now()
        chat_session.has_unanswered = True
        await chat_session.save()

        print(f"✅ Сообщение пользователя {user_id} сохранено в сессию {claim_id} "
              f"({'текст' if message.text else 'фото' if message.photo else 'документ'})")



    except Exception as e:
        print(f"❌ Ошибка сохранения сообщения пользователя: {e}")
        import traceback
        traceback.print_exc()
