import json
from pathlib import Path
from urllib.parse import quote
from fastapi.responses import StreamingResponse
import httpx
from aiogram.types import BufferedInputFile
from beanie import PydanticObjectId
from core.logger import api_logger as logger
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response, RedirectResponse
from api.router.auth import get_current_admin
from api.schemas.response import ClaimResponse, ChatMessageSchema, CloseChatRequest
from fastapi import Form, UploadFile, File
from config import cnf
from core.bot import bot
from db.beanie.models import Claim, UserMessage, ChatSession, User, AdminMessage
from db.beanie.models.models import ChatMessage, KonsolPayment, SupportSession
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

        logger.info(f"✅ Bank updated for claim {claim_id}: {bank_member_id}")

        return {
            "ok": True,
            "claim_id": claim_id,
            "bank_member_id": bank_member_id
        }

    except Exception as e:
        logger.error(f"❌ Ошибка обновления банка: {e}")
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
        has_unanswered: Optional[bool] = Query(None),  # Новый параметр фильтрации
        admin=Depends(get_current_admin)
):
    if not admin:
        return RedirectResponse("/auth/login")

    query = {"process_status": "complete"}

    if user_id:
        query["user_id"] = user_id
    if status:
        query["claim_status"] = status

    if number and number.strip():
        try:
            number_int = int(number.strip())
            claim_id_str = f"{number_int:06d}"
            query["claim_id"] = {"$regex": f"^{claim_id_str}$"}
        except ValueError:
            pass

    claims_query = Claim.find(query)

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

    # Получаем все заявки
    claims = await claims_query.sort("-created_at").to_list()

    # Фильтрация по has_unanswered
    if has_unanswered is not None:
        filtered_claims = []
        for claim in claims:
            # Находим активную сессию чата для заявки
            chat_session = await ChatSession.find_one(
                {"claim_id": claim.claim_id, "is_active": True}
            )

            # Фильтруем в зависимости от значения has_unanswered
            if has_unanswered:
                # Показываем только заявки с неотвеченными сообщениями
                if chat_session and chat_session.has_unanswered:
                    filtered_claims.append(claim)
            else:
                # Показываем только заявки без неотвеченных сообщений
                if not chat_session or not chat_session.has_unanswered:
                    filtered_claims.append(claim)

        claims = filtered_claims

    user_ids = list(set([claim.user_id for claim in claims]))
    user_claims_count = {}
    for uid in user_ids:
        count = await Claim.find({"user_id": uid, "process_status": "complete"}).count()
        user_claims_count[str(uid)] = count

    claims_data = []
    for claim in claims:
        user_id_str = str(claim.user_id)
        total_claims = user_claims_count.get(user_id_str, 1)
        user = await get_user_safe(claim.user_id)

        # 🔍 Проверка активной сессии поддержки
        active_support = await SupportSession.find_one(
            SupportSession.user_id == claim.user_id,
            SupportSession.resolved == False
        )
        has_active_support_session = active_support is not None

        chat_session = await ChatSession.find_one(
            {"claim_id": claim.claim_id, "is_active": True}
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
            "old_claims": total_claims,
            "has_active_support_session": has_active_support_session,
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
        "has_unanswered": has_unanswered,  # Передаем значение в шаблон
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

        # 🔍 Проверяем, есть ли у пользователя ОТКРЫТАЯ support-сессия
        active_support_session = await SupportSession.find_one(
            SupportSession.user_id == claim.user_id,
            SupportSession.resolved == False
        )
        if active_support_session:
            warning_msg = (
                "У пользователя есть открытая сессия в технической поддержке. "
                "Отправка сообщения невозможна, пока сессия не будет закрыта."
            )
            logger.warning(
                f"⚠️ [ChatSend] claim_id={claim_id}, user_id={claim.user_id} — "
                f"активная SupportSession (id={active_support_session.id}). Отмена отправки."
            )
            raise HTTPException(status_code=409, detail=warning_msg)  # 409 Conflict

        # ✅ Продолжаем отправку — активной сессии нет
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
        msg = ChatMessage(
            session_id=claim_id,
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

        # Обновляем сессию чата
        session = await ChatSession.find_one({"claim_id": claim_id})
        if session:
            session.last_interaction = datetime.now()
            session.has_unanswered = False
            await session.save()

        return {"ok": True, "message_id": str(msg.id)}

    except HTTPException:
        raise  # прокидываем HTTP-ошибки выше
    except Exception as e:
        error_msg = f"Ошибка отправки сообщения: {str(e)}"
        logger.error(f"❌ [ChatSend] {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)


from aiogram.types import BufferedInputFile
import mimetypes
from datetime import datetime


@router.post("/chat/send-file")
async def send_chat_file_endpoint(
    claim_id: str = Form(...),
    file: UploadFile = File(...),
    caption: str = Form(""),
    admin=Depends(get_current_admin)
):
    # 1. Проверка заявки
    claim = await Claim.find_one({"claim_id": claim_id})
    if not claim:
        raise HTTPException(404, "Claim not found")

    # 2. Проверка support-сессии
    active_support = await SupportSession.find_one(
        SupportSession.user_id == claim.user_id,
        SupportSession.resolved == False
    )
    if active_support:
        raise HTTPException(409, "У пользователя есть открытая сессия в техподдержке")

    # 3. Чтение файла
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(400, "Файл слишком большой (макс. 50 МБ)")

    filename = file.filename or "file"
    mime_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    input_file = BufferedInputFile(contents, filename=filename)

    # 4. Отправка в Telegram
    file_id = ""
    is_photo = False
    msg = None
    try:
        if mime_type.startswith("image/"):
            msg = await bot.send_photo(
                chat_id=claim.user_id,
                photo=input_file,
                caption=caption[:1024] or None
            )
            file_id = msg.photo[-1].file_id if msg.photo else ""
            is_photo = True
        else:
            msg = await bot.send_document(
                chat_id=claim.user_id,
                document=input_file,
                caption=caption[:1024] or None
            )
            file_id = msg.document.file_id if msg.document else ""
    except Exception as e:
        logger.error(f"❌ Telegram send failed: {e}")
        caption += " (не доставлено)"

    # 5. 🔥 Сохраняем в СУЩЕСТВУЮЩУЮ модель ChatMessage:
    #    - фото → has_photo=True, photo_file_id=file_id
    #    - документ → has_photo=False, photo_file_id=file_id (да, так!)
    chat_msg = ChatMessage(
        session_id=claim_id,
        claim_id=claim_id,
        user_id=claim.user_id,
        message=caption or filename,
        is_bot=True,
        has_photo=is_photo,          # ← true только для фото
        photo_file_id=file_id,       # ← file_id документа тоже сюда!
        photo_caption=caption if is_photo else None,
        timestamp=datetime.now()
    )
    await chat_msg.insert()

    # 6. Обновляем сессию
    session = await ChatSession.find_one({"claim_id": claim_id})
    if session:
        session.last_interaction = datetime.now()
        session.has_unanswered = False
        await session.save()

    return {
        "ok": True,
        "message_id": str(chat_msg.id),
        "file_type": "photo" if is_photo else "document"
    }

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
        try:
            file = await bot.get_file(message.photo_file_id)
        except Exception as e:
            logger.warning(f"Telegram get_file failed for {message.photo_file_id}: {e}")
            raise HTTPException(400, "Invalid or expired file_id")
        if not file.file_path:
            raise HTTPException(status_code=500, detail="File path missing from Telegram")

        # 3. Формируем публичный URL
        photo_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"

        return {"url": photo_url}

    except Exception as e:
        logger.error(f"❌ Ошибка в /chat/photo-url/{message_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get photo URL")


@router.get("/chat/download/{message_id}")
async def download_chat_file(message_id: str, admin=Depends(get_current_admin)):
    """
    Универсальный эндпоинт для скачивания файлов (фото и документов) из ChatMessage.
    """
    try:
        # 1. Получаем сообщение
        obj_id = PydanticObjectId(message_id)
        msg = await ChatMessage.get(obj_id)
        if not msg or not msg.photo_file_id:
            raise HTTPException(404, "Файл не найден")

        # 2. Получаем file_path из Telegram
        file_info = await bot.get_file(msg.photo_file_id)
        if not file_info.file_path:
            raise HTTPException(500, "File path missing from Telegram")

        file_url = f"https://api.telegram.org/file/bot{bot.token}/{file_info.file_path}"

        # 3. Скачиваем через httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(file_url)
            if resp.status_code != 200:
                raise HTTPException(502, "Не удалось получить файл из Telegram")

            # 4. Определяем имя файла
            filename = "file"

            # Если есть сообщение, используем первую строку как имя файла
            if msg.message and msg.message.strip():
                first_line = msg.message.strip().split('\n')[0].strip()
                if first_line and len(first_line) <= 60:
                    filename = first_line

            # Убираем недопустимые символы
            filename = "".join(c if c.isalnum() or c in "._- " else "_" for c in filename)
            if not filename.strip():
                filename = "file"

            # 5. Определяем Content-Type и расширение
            content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()

            # Расширения для разных типов файлов
            ext_map = {
                "image/jpeg": ".jpg",
                "image/jpg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "application/pdf": ".pdf",
                "application/zip": ".zip",
                "application/x-rar-compressed": ".rar",
                "application/msword": ".doc",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                "application/vnd.ms-excel": ".xls",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                "text/plain": ".txt",
                "text/csv": ".csv",
                "application/json": ".json",
                "audio/mpeg": ".mp3",
                "audio/wav": ".wav",
                "video/mp4": ".mp4",
                "video/avi": ".avi",
                "video/quicktime": ".mov",
            }

            # Добавляем расширение, если его нет в имени файла
            ext = ext_map.get(content_type, "")
            if ext and not filename.lower().endswith(tuple(ext_map.values())):
                filename += ext

            # 6. Заголовки и поток
            headers = {
                "Content-Type": content_type,
                "Content-Disposition": f'attachment; filename="{quote(filename)}"',
                "Cache-Control": "private, max-age=300",
            }

            async def stream_file():
                async for chunk in resp.aiter_bytes(65536):
                    yield chunk

            return StreamingResponse(stream_file(), headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ download_chat_file({message_id}): {e}", exc_info=True)
        raise HTTPException(500, "Внутренняя ошибка сервера")

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
            await close_chat_session(claim_id, claim.user_id)  # Передаем user_id

        logger.info(f"✅ Статус заявки {claim_id} обновлен на {new_status}")

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
        logger.info(f"🔍 [ADMIN] Подтверждение заявки: {claim.claim_id}")

        # === Получаем пользователя ===
        user = await User.get(tg_id=claim.user_id)
        if not user:
            logger.error(f"❌ [ADMIN] Пользователь не найден: {claim.user_id}")
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
            logger.info(f"✅ [ADMIN] Contract_id создан: {contractor_id}")

        except Exception as e:
            logger.error(f"❌ [ADMIN] Ошибка создания contract_id: {e}")
            return False

        # === 2. Подготавливаем данные для платежа ===
        bank_details_kind = "fps" if claim.phone else "card"

        if bank_details_kind == "fps":
            if not claim.bank_member_id:
                logger.error(f"❌ [ADMIN] Не указан ID банка для СБП: {claim.claim_id}")
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

            logger.info(f"✅ [ADMIN] Платёж создан: {payment_id}")

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
                    text="✅ Ваш выигрыш отправлен на указанные реквизиты.\nКомпания Pure желает вам крепкого здоровья и отличного дня!"
                )
                logger.info(f"✅ [ADMIN] Уведомление отправлено пользователю {claim.user_id}")
            except Exception as notify_e:
                logger.error(f"⚠️ [ADMIN] Не удалось уведомить пользователя: {notify_e}")

            return True

        except Exception as pay_e:
            logger.error(f"❌ [ADMIN] Ошибка создания платежа: {pay_e}")
            return False

    except Exception as e:
        logger.error(f"❌ [ADMIN] Общая ошибка подтверждения заявки: {e}")
        import traceback
        traceback.print_exc()
        return False


@router.post("/chat/close/")
async def close_chat_session_api(request: CloseChatRequest):
    """API endpoint для закрытия чат-сессии"""
    try:
        # Получаем user_id из базы данных по claim_id
        from db.beanie.models.models import ChatSession, Claim

        # Находим заявку чтобы получить user_id
        claim = await Claim.find_one({"claim_id": request.claim_id})
        if not claim:
            raise HTTPException(status_code=404, detail="Заявка не найдена")

        user_id = claim.user_id

        # Закрываем чат-сессию
        await close_chat_session(request.claim_id, user_id)
        return {"success": True, "message": "Чат успешно завершен"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка закрытия чата: {str(e)}")

async def close_chat_session(claim_id: str, user_id: int = None):
    """Закрытие чат-сессии для заявки с отправкой уведомления пользователю"""
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

            logger.info(f"✅ Чат-сессия закрыта для заявки {claim_id}")

            # Отправляем уведомление пользователю в Telegram
            if user_id:
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text="💬 Чат с администратором завершен."
                    )
                    logger.info(f"✅ Уведомление отправлено пользователю {user_id}")
                except Exception as tg_error:
                    logger.error(f"❌ Ошибка отправки уведомления в Telegram: {tg_error}")
                finally:
                    await bot.session.close()

        else:
            logger.info(f"ℹ️ Активная чат-сессия не найдена для заявки {claim_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка закрытия чат-сессии: {e}")
        raise


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

        logger.warning(f"🚫 Пользователь заблокирован {user_id} через админ-панель")

        return {
            "ok": True,
            "message": f"Пользователь {user_id} заблокирован",
            "user_id": user_id,
            "banned": True
        }

    except Exception as e:
        logger.error(f"❌ Ошибка блокировки пользователя: {e}")
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

        logger.warning(f"✅ Пользователь разблокирован {user_id} через админ-панель")

        return {
            "ok": True,
            "message": f"Пользователь {user_id} разблокирован",
            "user_id": user_id,
            "banned": False
        }

    except Exception as e:
        logger.error(f"❌ Ошибка разблокировки пользователя: {e}")
        return {"ok": False, "error": str(e)}