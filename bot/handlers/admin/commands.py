import asyncio
from datetime import datetime
from decimal import Decimal
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ForceReply
from bot.templates.admin import menu as tadmin
from bot.templates.admin.menu import AdminState
from db.beanie.models import Claim, KonsolPayment, User
from core.bot import bot
from db.beanie.models.models import ChatSession
from utils.konsol_client import konsol_client

router = Router()

# --- 1. Обработка нажатия "Заполнить ID банка" ---
@router.callback_query(F.data.startswith("fill_bank_id_"))
async def request_bank_id(call: CallbackQuery, state: FSMContext):
    """Запрашивает у админа ID банка для заявки СБП"""
    claim_id = call.data.replace("fill_bank_id_", "")
    await state.update_data(pending_claim_id=claim_id)
    await state.set_state(AdminState.waiting_for_bank_id)

    # Отправляем сообщение
    await call.message.reply(
        text="<b>Введите ID банка:</b>",
        parse_mode="HTML",
        reply_markup=ForceReply(selective=True, input_field_placeholder="Введите ID банка...")
    )
    await call.answer()

# --- 2. Прием ID банка  ---
@router.message(StateFilter(AdminState.waiting_for_bank_id))
async def receive_bank_id(msg: Message, state: FSMContext):
    """Принимает ID банка от админа и сохраняет его в заявке"""
    if not msg.text:
        await msg.answer(
            "❌ Пожалуйста, отправьте корректный ID банка."
        )
        return

    data = await state.get_data()
    claim_id = data.get("pending_claim_id")

    if not claim_id:
        await msg.answer("❌ Ошибка: ID заявки не найден. Попробуйте снова.")
        await state.clear()
        return

    bank_member_id = msg.text.strip()

    # Найдем заявку
    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        await msg.answer("❌ Заявка не найдена.")
        await state.clear()
        return

    # Проверим, что это заявка СБП
    if not claim.phone:
        await msg.answer("❌ Эта заявка не является заявкой СБП.")
        await state.clear()
        return

    # Сохраним ID банка в заявке
    await claim.update(bank_member_id=bank_member_id)

    # Отправляем клавиатуру с подтверждением
    await msg.answer(
        text=f"✅ ID банка <code>{bank_member_id}</code> сохранен для заявки <b>{claim_id}</b>.",
        parse_mode="HTML")

    await state.clear()

# --- 3. Обработка подтверждения оплаты (создание платежа) ---
@router.callback_query(F.data.startswith("confirm_"))
async def handle_confirm_action(call: CallbackQuery):
    """Обработка кнопки '✅ Подтвердить оплату'"""
    claim_id = call.data.replace("confirm_", "")
    print(f"✅ Подтверждение оплаты для заявки: {claim_id}")

    await process_claim_approval(call, claim_id)

# --- 4. Обработка отклонения ---
@router.callback_query(F.data.startswith("reject_"))
async def handle_reject_action(call: CallbackQuery):
    """Обработка кнопки '❌ Отклонить'"""
    claim_id = call.data.replace("reject_", "")
    print(f"❌ Отклонение заявки: {claim_id}")

    await process_claim_rejection(call, claim_id)

@router.callback_query(F.data.startswith("ban_"))
async def handle_ban_action(call: CallbackQuery):
    """Обработка кнопки '🚫 Заблокировать пользователя'"""
    claim_id = call.data.replace("ban_", "")
    claim = await Claim.get(claim_id=claim_id)
    user_id = claim.user_id


    await process_user_ban(call, user_id, claim_id)


async def process_user_ban(call: CallbackQuery, user_id: int, claim_id: str):
    """блокировка пользователя"""
    try:
        user = await User.get(tg_id=user_id)
        if not user:
            await call.answer("Пользователь не найден", show_alert=True)
            return

        if user.banned:
            await call.answer("Пользователь уже заблокирован", show_alert=True)
            return

        await user.update(banned=True)
        await call.answer("Пользователь заблокирован", show_alert=True)

        print(f"🚫 Пользователь заблокирован {user_id}")

        if call.message.photo:
            current_caption = call.message.caption or ""
            new_caption = f"🚫 Пользователь заблокирован\n\n{current_caption}"
            await call.message.edit_caption(caption=new_caption, reply_markup=tadmin.claim_action_ikb(claim_id))
        else:
            current_text = call.message.text or ""
            new_text = f"🚫 Пользователь заблокирован\n\n{current_text}"
            await call.message.edit_text(text=new_text, reply_markup=tadmin.claim_action_ikb(claim_id))

    except Exception as e:
        print(f"❌ Ошибка блокировки пользователя: {e}")
        import traceback
        traceback.print_exc()
        await call.answer("Ошибка блокировки пользователя", show_alert=True)


async def process_claim_approval(call: CallbackQuery, claim_id: str):
    """Обработка подтверждения заявки: создание НОВОГО контрактора и платежа"""
    try:
        claim = await Claim.get(claim_id=claim_id)
        if not claim:
            await call.answer("Заявка не найдена", show_alert=True)
            return

        print(f"🔍 Найдена заявка: {claim.claim_id}, текущий статус: {claim.claim_status}")

        # === Получаем пользователя ===
        user = await User.get(tg_id=claim.user_id)
        if not user:
            await call.answer("Пользователь не найден", show_alert=True)
            return

        # === 1. Создаём НОВОГО contract_id в Konsol API ===
        # Определяем телефон для contract_id
        if claim.phone:
            # Если СБП - используем реальный телефон из заявки
            contractor_phone = claim.phone
        else:
            # Если карта - используем заглушку
            contractor_phone = "+79000" + claim.claim_id

        contractor_data = {
            "kind": "individual",
            "first_name": claim.claim_id,
            "last_name": "Заявка",
            "phone": contractor_phone
        }

        try:
            contractor_result = await konsol_client.create_contractor(contractor_data)
            contractor_id = contractor_result["id"]

            # === Сохраняем contractor_id в ЗАЯВКЕ ===
            await claim.update(contractor_id=contractor_id)

            print(f"[CONTRACTOR] Новый contract_id создан для заявки {claim.claim_id}: {contractor_id}")

        except Exception as e:
            error_msg = f"[CONTRACTOR ERROR] Не удалось создать contract_id для заявки {claim.claim_id}: {e}"
            print(error_msg)
            await call.message.answer(error_msg)
            await call.answer("Ошибка создания contract_id", show_alert=True)
            return # Прерываем обработку, если contract_id не создан

        # === 2. Подготавливаем данные для платежа ===
        bank_details_kind = "fps" if claim.phone else "card"

        if bank_details_kind == "fps":
            if not claim.bank_member_id:
                await call.answer("❌ Необходимо указать ID банка для СБП!", show_alert=True)
                return
            bank_details = {
                "fps_mobile_phone": claim.phone,
                "fps_bank_member_id": claim.bank_member_id
            }
        else:
            bank_details = {
                "card_number": claim.card
            }

        payment_data = {
            "contractor_id": contractor_id, # Используем НОВЫЙ contractor_id из заявки
            "services_list": [
                {
                    "title": f"Выплата по заявке {claim.claim_id}",
                    "amount": str(claim.amount)
                }
            ],
            "bank_details_kind": bank_details_kind,
            "bank_details": bank_details,
            "purpose": "Выплата выигрыша",
            "amount": str(claim.amount)
        }

        # === 3. Создаём платёж в Konsol API ===
        try:
            result = await konsol_client.create_payment(payment_data)
            payment_id = result.get("id")
            payment_status = result.get("status")

            print(f"[PAYMENT] Платёж создан для заявки {claim.claim_id}: {payment_id}")

            # === 4. Сохраняем платёж в БД ===
            await KonsolPayment.create(
                konsol_id=payment_id,
                contractor_id=contractor_id, # НОВЫЙ contractor_id
                amount=claim.amount,
                status=payment_status,
                purpose=payment_data["purpose"],
                services_list=payment_data["services_list"],
                bank_details_kind=bank_details_kind,
                card_number=claim.card,
                phone_number=claim.phone,
                bank_member_id=claim.bank_member_id,
                claim_id=claim.claim_id,
                user_id=claim.user_id
            )

            # === 5. Обновляем статусы в заявке ===
            await claim.update(
                claim_status="confirm",
                process_status="complete",
                konsol_payment_id=payment_id,
                updated_at=datetime.utcnow()
            )

            # === 6. Обновляем сообщение в группе ===
            if call.message.photo:
                current_caption = call.message.caption or ""
                new_caption = f"{current_caption[:-14]} Подтверждено ✅"
                await call.message.edit_caption(caption=new_caption, reply_markup=None)
            else:
                current_text = call.message.text or ""
                new_text = f"{current_text[:-14]} Подтверждено ✅"
                await call.message.edit_text(text=new_text, reply_markup=None)



            # === 7. Уведомляем пользователя ===
            try:
                await bot.send_message(
                    chat_id=claim.user_id,
                    text="✅ Ваш выигрыш отправлен на указанные реквизиты. Компания Pure желает Вам крепкого здоровья, и хорошего дня."
                )
            except Exception as notify_e:
                print(f"[NOTIFY ERROR] Не удалось уведомить пользователя {claim.user_id}: {notify_e}")

            await call.answer("✅ Оплата подтверждена")

            try:
                # ✅ ЗАКРЫВАЕМ ЧАТ-СЕССИЮ
                session = await ChatSession.find_one(
                    ChatSession.claim_id == claim_id,
                    ChatSession.is_active == True
                )
                if session:
                    await session.update(
                        is_active=False,
                        closed_at=datetime.now()
                    )
                    # Уведомляем в чате если он открыт
                    if session.admin_chat_id:
                        await bot.send_message(
                            chat_id=session.admin_chat_id,
                            text="❌ <b>Чат закрыт - заявка обработана</b>",
                            parse_mode="HTML"
                        )
            except Exception as e:
                return

        except Exception as pay_e:
            error_msg = f"[PAYMENT ERROR] Ошибка создания платежа для заявки {claim.claim_id}: {pay_e}"
            print(error_msg)
            await call.message.answer(error_msg)
            await call.answer("Ошибка создания платежа", show_alert=True)

    except Exception as e:
        print(f"❌ Ошибка подтверждения заявки {claim_id}: {e}")
        import traceback
        traceback.print_exc()
        await call.answer("Ошибка подтверждения", show_alert=True)

# --- 6. Логика отклонения ---
async def process_claim_rejection(call: CallbackQuery, claim_id: str):
    """Обработка отклонения заявки"""
    try:
        claim = await Claim.get(claim_id=claim_id)
        if not claim:
            await call.answer("Заявка не найдена", show_alert=True)
            return

        # Обновляем статус заявки
        await claim.update(
            claim_status="cancelled",
            process_status="cancelled",
            updated_at=datetime.utcnow()
        )

        # Обновляем сообщение в группе
        if call.message.photo:
            current_caption = call.message.caption or ""
            new_caption = f"{current_caption[:-14]} Отклонено ❌"
            await call.message.edit_caption(caption=new_caption, reply_markup=None)
        else:
            current_text = call.message.text or ""
            new_text = f"{current_text[:-14]} Отклонено ❌"
            await call.message.edit_text(text=new_text, reply_markup=None)

        print(f"✏️ Сообщение обновлено (отклонено)")

        # Уведомление пользователю если нужно
        # try:
        #     await bot.send_message(
        #         chat_id=claim.user_id,
        #         text="❌ Ваша заявка отклонена."
        #     )
        # except Exception as e:
        #     print(f"[NOTIFY ERROR] Не удалось уведомить пользователя {claim.user_id}: {e}")
        #
        await call.answer("❌ Заявка отклонена")

        try:
            # ✅ ЗАКРЫВАЕМ ЧАТ-СЕССИЮ
            session = await ChatSession.find_one(
                ChatSession.claim_id == claim_id,
                ChatSession.is_active == True
            )
            if session:
                await session.update(
                    is_active=False,
                    closed_at=datetime.now()
                )
                # Уведомляем в чате если он открыт
                if session.admin_chat_id:
                    await bot.send_message(
                        chat_id=session.admin_chat_id,
                        text="❌ <b>Чат закрыт - заявка обработана</b>",
                        parse_mode="HTML"
                    )
        except Exception as e:
            return

    except Exception as e:
        print(f"❌ Ошибка отклонения заявки: {e}")
        await call.answer("❌ Ошибка отклонения", show_alert=True)
