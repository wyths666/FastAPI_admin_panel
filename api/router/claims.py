import json
from pathlib import Path
from beanie import PydanticObjectId
from core.logger import api_logger as logger
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response, RedirectResponse
from api.router.auth import get_current_admin
from api.schemas.response import ClaimResponse, ChatMessageSchema

from config import cnf
from core.bot import bot
from db.beanie.models import Claim, UserMessage, ChatSession, User, AdminMessage
from db.beanie.models.models import ChatMessage, KonsolPayment
from utils.konsol_client import konsol_client

router = APIRouter(prefix="/claims", tags=["Claims"])
templates = Jinja2Templates(directory="api/templates")

# --- Помощь: получить пользователя по tg_id ---
async def get_user_safe(tg_id: int) -> Optional[User]:
    try:
        # ПРАВИЛЬНЫЙ СИНТАКСИС
        user = await User.find_one({"tg_id": tg_id})  # ← словарь
        return user
    except Exception:
        return None


def load_banks():
    banks_file = Path("utils/banks.json")
    if banks_file.exists():
        with open(banks_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


@router.post("/update_bank")
async def update_claim_bank(data: dict):
    """Обновление bank_member_id для заявки"""
    try:
        claim_id = data.get("claim_id")
        bank_member_id = data.get("bank_member_id")

        if not claim_id:
            raise HTTPException(status_code=400, detail="claim_id required")

        # Находим заявку
        claim = await Claim.find_one({"claim_id": claim_id})
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")

        # Обновляем bank_member_id
        await claim.update(bank_member_id=bank_member_id)

        print(f"✅ Bank updated for claim {claim_id}: {bank_member_id}")

        return {
            "ok": True,
            "claim_id": claim_id,
            "bank_member_id": bank_member_id
        }

    except Exception as e:
        print(f"❌ Ошибка обновления банка: {e}")
        return {"ok": False, "error": str(e)}

# --- 1. Страница списка заявок ---
@router.get("/", response_class=HTMLResponse)
async def claims_page(
        request: Request,
        user_id: Optional[int] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        number: Optional[str] = Query(None),
        admin=Depends(get_current_admin)
):
    if not admin:
        return RedirectResponse("/auth/login")

    query = {}  # начинаем с пустого словаря

    # Фильтр по пользователю
    if user_id:
        query["user_id"] = user_id

    # Фильтр по статусу
    if status:
        query["claim_status"] = status

    if number and number.strip():  # ← проверяем что строка не пустая
        try:
            number_int = int(number.strip())
            claim_id_str = f"{number_int:06d}"
            query["claim_id"] = {"$regex": f"^{claim_id_str}$"}
        except ValueError:
            # Если не число, игнорируем
            pass

    # Базовый запрос
    claims_query = Claim.find(query)

    # Фильтр по дате (отдельно, т.к. это диапазон)
    if date_from:
        try:
            dt = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
            claims_query = claims_query.find(Claim.created_at >= dt)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.fromisoformat(date_to).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            claims_query = claims_query.find(Claim.created_at <= dt)
        except ValueError:
            pass

    claims = await claims_query.sort("-created_at").to_list()

    # СОБИРАЕМ ID всех пользователей в текущей выборке
    user_ids = list(set([claim.user_id for claim in claims]))

    # АГРЕГАЦИЯ: подсчитываем заявки для каждого пользователя
    user_claims_count = {}
    for user_id in user_ids:
        count = await Claim.find({"user_id": user_id}).count()
        user_claims_count[str(user_id)] = count


    # Подготавливаем данные
    claims_data = []
    for claim in claims:
        user_id_str = str(claim.user_id)
        total_claims = user_claims_count.get(user_id_str, 1)
        previous_claims = total_claims - 1
        user = await get_user_safe(claim.user_id)

        # ПРАВИЛЬНЫЙ СИНТАКСИС ДЛЯ ПОИСКА ЧАТ-СЕССИИ
        chat_session = await ChatSession.find_one(
            {"claim_id": claim.claim_id, "is_active": True}  # ← словарь
        )

        claims_data.append({
            "id": str(claim.id),
            "claim_id": claim.claim_id,
            "user_id": claim.user_id,
            "banned": user.banned,
            "username": user.username if user else f"@id{claim.user_id}",
            "code": claim.code.upper(),
            "payment_method": claim.payment_method,
            "phone": claim.phone,
            "bank": claim.bank,
            "card": claim.card,
            "bank_member_id": claim.bank_member_id,
            "review_text": claim.review_text,
            "photo_count": len(claim.photo_file_ids),
            "photo_file_ids": claim.photo_file_ids,
            "claim_status": claim.claim_status,
            "process_status": claim.process_status,
            "created_at": claim.created_at,
            "is_chat_active": chat_session is not None,
            "has_unanswered": chat_session.has_unanswered if chat_session else False,
            "old_claims": total_claims
        })

    banks = load_banks()

    return templates.TemplateResponse("claims.html", {
        "request": request,
        "claims": claims_data,
        "banks": banks,
        "user_id": user_id,
        "date_from": date_from,
        "date_to": date_to,
        "status": status,
        "number": number,
        "statuses": [
            {"id": "pending", "name": "✅ Подтверждёно"},
            {"id": "process", "name": "🆕 Не обработано"},
            {"id": "cancelled", "name": "❌ Отменёно"},
        ]
    })

# --- 2. API: создать чат-сессию ---
@router.post("/chat/start")
async def start_chat_session(data: dict):
    claim_id = data.get("claim_id")
    if not claim_id:
        raise HTTPException(status_code=400, detail="claim_id required")

    # ПРАВИЛЬНЫЙ СИНТАКСИС
    claim = await Claim.find_one({"claim_id": claim_id})  # ← словарь
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Создаём или активируем сессию - ПРАВИЛЬНЫЙ СИНТАКСИС
    session = await ChatSession.find_one(
        {"claim_id": claim_id, "is_active": True}  # ← словарь
    )

    if not session:
        session = ChatSession(
            claim_id=claim_id,
            user_id=claim.user_id,
            is_active=True,
            has_unanswered=False
        )
        await session.insert()



    return {"ok": True, "session_id": str(session.id)}


# --- 3. API: получить историю чата по заявке ---
@router.get("/chat/history")
async def chat_history_endpoint(claim_id: str):
    # ПРАВИЛЬНЫЙ СИНТАКСИС ДЛЯ BEANIE
    messages = await ChatMessage.find(
        {"claim_id": claim_id}  # ← используем словарь вместо точечной нотации
    ).sort("timestamp").to_list()

    result = [
        ChatMessageSchema(
            id=str(msg.id),
            claim_id=msg.claim_id,
            user_id=msg.user_id,
            message=msg.message,
            is_bot=msg.is_bot,
            has_photo=msg.has_photo,
            photo_file_id=msg.photo_file_id,
            photo_caption=msg.photo_caption,
            timestamp=msg.timestamp
        ).model_dump()
        for msg in messages
    ]
    return result


# --- 4. API: отправить сообщение (админ → пользователь) ---
@router.post("/chat/send")
async def send_chat_message_endpoint(data: dict):
    claim_id = data.get("claim_id")
    text = data.get("text", "").strip()
    is_bot = data.get("is_bot", True)
    has_photo = data.get("has_photo", False)
    photo_file_id = data.get("photo_file_id")
    photo_caption = data.get("photo_caption", "")


    if not claim_id or (not text and not has_photo):
        error_msg = "claim_id and text or photo required"
        logger.error(f"❌ [ChatSend] {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)

    try:
        # Ищем заявку
        claim = await Claim.find_one({"claim_id": claim_id})
        if not claim:
            error_msg = f"Claim {claim_id} not found"
            logger.error(f"❌ [ChatSend] {error_msg}")
            raise HTTPException(status_code=404, detail=error_msg)


        # Отправляем в Telegram
        if has_photo and photo_file_id:
            logger.info(f"📸 [ChatSend] Отправка фото: file_id={photo_file_id}")
            await bot.send_photo(
                chat_id=claim.user_id,
                photo=photo_file_id,
                caption=text if text else None
            )
        else:
            logger.info(f"💬 [ChatSend] Отправка текста: '{text}'")
            await bot.send_message(chat_id=claim.user_id, text=text)


        # Сохраняем в БД
        try:
            msg = ChatMessage(
                session_id=claim_id,  # используем claim_id как session_id
                claim_id=claim_id,
                user_id=claim.user_id,
                message=text,
                is_bot=is_bot,
                has_photo=has_photo,
                photo_file_id=photo_file_id,
                photo_caption=photo_caption,
                timestamp=datetime.now()
            )
            await msg.insert()

        except Exception as db_error:
            logger.error(f"❌ [ChatSend] Ошибка сохранения в БД: {db_error}")
            # НЕ выбрасываем исключение, т.к. сообщение уже отправлено в Telegram
            # Просто логируем ошибку

        # Обновляем сессию
        try:
            session = await ChatSession.find_one({"claim_id": claim_id})
            if session:
                session.last_interaction = datetime.now()
                session.has_unanswered = False  # сбрасываем т.к. админ ответил
                await session.save()
        except Exception as session_error:
            logger.error(f"⚠️ [ChatSend] Ошибка обновления сессии: {session_error}")

        return {"ok": True, "message_id": str(msg.id) if 'msg' in locals() else "unknown"}

    except Exception as e:
        error_msg = f"Ошибка отправки сообщения: {str(e)}"
        logger.error(f"❌ [ChatSend] {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/chat/photo-url/{message_id}")
async def get_chat_photo_url(message_id: str):
    """
    Возвращает JSON с URL фото из Telegram CDN по message_id.
    Без скачивания, быстро и безопасно.
    """
    try:
        # 1. Валидация и получение сообщения
        obj_id = PydanticObjectId(message_id)
        message = await ChatMessage.get(obj_id)

        if not message or not message.has_photo or not message.photo_file_id:
            raise HTTPException(status_code=404, detail="Photo not found in message")

        # 2. Получаем file_path через Telegram API (лёгкий запрос, без скачивания!)
        file = await bot.get_file(message.photo_file_id)  # ← это НЕ download_file, а мета-запрос
        if not file.file_path:
            raise HTTPException(status_code=500, detail="File path missing from Telegram")

        # 3. Формируем публичный URL
        photo_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"

        return {"url": photo_url}

    except Exception as e:
        print(f"❌ Ошибка в /chat/photo-url/{message_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get photo URL")



# --- 5. API: изменить статус заявки ---
@router.post("/status/update")
async def update_claim_status(data: dict):
    try:
        claim_id = data.get("claim_id")
        new_status = data.get("new_status")
        close_chat = data.get("close_chat", True)

        if not claim_id or not new_status:
            raise HTTPException(status_code=400, detail="claim_id and new_status required")

        # Находим заявку
        claim = await Claim.find_one({"claim_id": claim_id})
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")

        valid_statuses = ["pending", "confirm", "cancelled"]
        if new_status not in valid_statuses:
            raise HTTPException(status_code=400, detail="Invalid status")

        # === ОСОБАЯ ЛОГИКА ДЛЯ СТАТУСА PENDING ===
        if new_status == "pending":
            # Проверяем, не был ли уже создан платеж
            if claim.konsol_payment_id:
                return {
                    "ok": False,
                    "error": "Платеж уже создан для этой заявки",
                    "claim_id": claim_id
                }

            # Выполняем логику подтверждения заявки
            success = await process_claim_approval_admin(claim)
            if not success:
                return {
                    "ok": False,
                    "error": "Ошибка создания платежа",
                    "claim_id": claim_id
                }

        else:
            # Для других статусов просто обновляем
            await claim.update(
                claim_status=new_status,
                process_status="complete" if new_status != "pending" else "process"
            )

        # Закрываем чат-сессию если нужно
        if close_chat:
            await close_chat_session(claim_id)

        logger.info(f"✅ Статус заявки {claim_id} обновлен на {new_status}, чат закрыт: {close_chat}")

        return {
            "ok": True,
            "claim_id": claim_id,
            "status": new_status,
            "chat_closed": close_chat
        }

    except Exception as e:
        logger.error(f"❌ Ошибка обновления статуса: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_claim_approval_admin(claim: Claim):
    """Обработка подтверждения заявки через админ-панель"""
    try:
        print(f"🔍 [ADMIN] Подтверждение заявки: {claim.claim_id}")

        # === Получаем пользователя ===
        user = await User.get(tg_id=claim.user_id)
        if not user:
            print(f"❌ [ADMIN] Пользователь не найден: {claim.user_id}")
            return False

        # === 1. Создаём НОВОГО contract_id в Konsol API ===
        contractor_phone = claim.phone if claim.phone else "+79000" + claim.claim_id

        contractor_data = {
            "kind": "individual",
            "first_name": claim.claim_id,
            "last_name": "Заявка",
            "phone": contractor_phone
        }

        try:
            contractor_result = await konsol_client.create_contractor(contractor_data)
            contractor_id = contractor_result["id"]

            # Сохраняем contractor_id в заявке
            await claim.update(contractor_id=contractor_id)
            print(f"✅ [ADMIN] Contract_id создан: {contractor_id}")

        except Exception as e:
            print(f"❌ [ADMIN] Ошибка создания contract_id: {e}")
            return False

        # === 2. Подготавливаем данные для платежа ===
        bank_details_kind = "fps" if claim.phone else "card"

        if bank_details_kind == "fps":
            if not claim.bank_member_id:
                print(f"❌ [ADMIN] Не указан ID банка для СБП: {claim.claim_id}")
                return False
            bank_details = {
                "fps_mobile_phone": claim.phone,
                "fps_bank_member_id": claim.bank_member_id
            }
        else:
            bank_details = {
                "card_number": claim.card
            }

        payment_data = {
            "contractor_id": contractor_id,
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

            print(f"✅ [ADMIN] Платёж создан: {payment_id}")

            # === 4. Сохраняем платёж в БД ===
            await KonsolPayment.create(
                konsol_id=payment_id,
                contractor_id=contractor_id,
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
                claim_status="pending",  # оставляем как pending для админ-панели
                process_status="complete",
                konsol_payment_id=payment_id,
                updated_at=datetime.utcnow()
            )

            # === 6. Уведомляем пользователя ===
            try:
                await bot.send_message(
                    chat_id=claim.user_id,
                    text="✅ Ваш выигрыш отправлен на указанные реквизиты. Компания Pure желает Вам крепкого здоровья, и хорошего дня."
                )
                print(f"✅ [ADMIN] Уведомление отправлено пользователю {claim.user_id}")
            except Exception as notify_e:
                print(f"⚠️ [ADMIN] Не удалось уведомить пользователя: {notify_e}")

            return True

        except Exception as pay_e:
            print(f"❌ [ADMIN] Ошибка создания платежа: {pay_e}")
            return False

    except Exception as e:
        print(f"❌ [ADMIN] Общая ошибка подтверждения заявки: {e}")
        import traceback
        traceback.print_exc()
        return False


async def close_chat_session(claim_id: str):
    """Закрытие чат-сессии для заявки"""
    try:
        # Находим активную сессию
        chat_session = await ChatSession.find_one({
            "claim_id": claim_id,
            "is_active": True
        })

        if chat_session:
            # Закрываем сессию
            chat_session.is_active = False
            chat_session.has_unanswered = False
            chat_session.closed_at = datetime.now()
            await chat_session.save()

            print(f"✅ Чат-сессия закрыта для заявки {claim_id}")

            # Уведомляем в админ-чате если он открыт
            if chat_session.admin_chat_id:
                try:
                    await bot.send_message(
                        chat_id=chat_session.admin_chat_id,
                        text=f"❌ <b>Чат закрыт - заявка {claim_id} обработана</b>",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    print(f"⚠️ Не удалось уведомить админа: {e}")

        else:
            print(f"ℹ️ Активная чат-сессия не найдена для заявки {claim_id}")

    except Exception as e:
        print(f"❌ Ошибка закрытия чат-сессии: {e}")


async def notify_user_about_chat_close(user_id: int, claim_id: str):
    """Уведомление пользователя о закрытии чата"""
    try:
        status_messages = {
            "confirm": "✅ Ваша заявка подтверждена",
            "cancelled": "❌ Ваша заявка отклонена",
            "pending": "⏳ Ваша заявка обработана"
        }

        message = f"{status_messages.get('pending', '📋 Ваша заявка обработана')}\n\n💬 Чат с поддержкой завершен. Если у вас есть новые вопросы, создайте новую заявку."

        await bot.send_message(chat_id=user_id, text=message)
        logger.info(f"✅ Уведомление о закрытии чата отправлено пользователю {user_id}")

    except Exception as e:
        logger.error(f"⚠️ Не удалось отправить уведомление пользователю {user_id}: {e}")

# Исправляем эндпоинт get_chat_photo



@router.get("/{claim_id}/photos/{photo_index}")
async def get_claim_photo(
        claim_id: str,
        photo_index: int,
        admin=Depends(get_current_admin)
):
    """Получить фото из заявки"""
    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    if not claim.photo_file_ids or photo_index >= len(claim.photo_file_ids):
        raise HTTPException(status_code=404, detail="Photo not found")

    photo_file_id = claim.photo_file_ids[photo_index]

    try:
        # Получаем файл из Telegram
        file = await bot.get_file(photo_file_id)
        file_path = file.file_path

        # Скачиваем файл
        file_bytes = await bot.download_file(file_path)

        return Response(
            content=file_bytes.getvalue(),
            media_type="image/jpeg",
            headers={"Content-Disposition": f"inline; filename=photo_{photo_index}.jpg"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading photo: {str(e)}")


@router.post("/user/ban")
async def ban_user(data: dict):
    """Блокировка пользователя"""
    try:
        user_id = data.get("user_id")
        claim_id = data.get("claim_id")

        if not user_id:
            return {"ok": False, "error": "user_id required"}

        # Находим пользователя
        user = await User.get(tg_id=user_id)
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}

        if user.banned:
            return {"ok": False, "error": "Пользователь уже заблокирован"}

        # Блокируем пользователя
        await user.update(banned=True)

        print(f"🚫 Пользователь заблокирован {user_id} через админ-панель")

        return {
            "ok": True,
            "message": f"Пользователь {user_id} заблокирован",
            "user_id": user_id,
            "banned": True
        }

    except Exception as e:
        print(f"❌ Ошибка блокировки пользователя: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/user/unban")
async def unban_user(data: dict):
    """Разблокировка пользователя"""
    try:
        user_id = data.get("user_id")
        claim_id = data.get("claim_id")

        if not user_id:
            return {"ok": False, "error": "user_id required"}

        # Находим пользователя
        user = await User.get(tg_id=user_id)
        if not user:
            return {"ok": False, "error": "Пользователь не найден"}

        if not user.banned:
            return {"ok": False, "error": "Пользователь не заблокирован"}

        # Разблокируем пользователя
        await user.update(banned=False)

        print(f"✅ Пользователь разблокирован {user_id} через админ-панель")

        return {
            "ok": True,
            "message": f"Пользователь {user_id} разблокирован",
            "user_id": user_id,
            "banned": False
        }

    except Exception as e:
        print(f"❌ Ошибка разблокировки пользователя: {e}")
        return {"ok": False, "error": str(e)}