import base64
import os

from core.logger import api_logger as logger
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import Response
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response, RedirectResponse
from api.router.auth import get_current_admin
from api.schemas.response import ClaimResponse, ChatMessageSchema

from config import cnf
from core.bot import bot
from db.beanie.models import Claim, UserMessage, ChatSession, User, AdminMessage
from db.beanie.models.models import ChatMessage

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


# --- 1. Страница списка заявок ---
@router.get("/", response_class=HTMLResponse)
async def claims_page(
        request: Request,
        user_id: Optional[int] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
):
    query = {}  # начинаем с пустого словаря

    # Фильтр по пользователю
    if user_id:
        query["user_id"] = user_id

    # Фильтр по статусу
    if status:
        query["claim_status"] = status

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

    # Подготавливаем данные
    claims_data = []
    for claim in claims:
        user = await get_user_safe(claim.user_id)

        # ПРАВИЛЬНЫЙ СИНТАКСИС ДЛЯ ПОИСКА ЧАТ-СЕССИИ
        chat_session = await ChatSession.find_one(
            {"claim_id": claim.claim_id, "is_active": True}  # ← словарь
        )

        claims_data.append({
            "id": str(claim.id),
            "claim_id": claim.claim_id,
            "user_id": claim.user_id,
            "username": user.username if user else f"@id{claim.user_id}",
            "code": claim.code,
            "payment_method": claim.payment_method,
            "phone": claim.phone,
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
        })

    return templates.TemplateResponse("claims.html", {
        "request": request,
        "claims": claims_data,
        "user_id": user_id,
        "date_from": date_from,
        "date_to": date_to,
        "status": status,
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


@router.get("/claims/chat/photo_url/{photo_file_id}")
async def get_chat_photo_url(photo_file_id: str):
    """Получить прямую ссылку на фото из Telegram"""
    try:
        print(f"🔗 Запрос URL для file_id: {photo_file_id}")

        from urllib.parse import unquote
        import aiohttp

        decoded_file_id = unquote(photo_file_id)


        async with aiohttp.ClientSession() as session:
            # Получаем информацию о файле
            tg_api_url = f"https://api.telegram.org/bot{cnf.bot.TOKEN}/getFile"

            async with session.post(tg_api_url, json={"file_id": decoded_file_id}) as resp:
                file_info = await resp.json()

            if not file_info.get('ok'):
                return {"error": "File not found in Telegram", "details": file_info}

            file_path = file_info['result']['file_path']
            direct_url = f"https://api.telegram.org/file/bot{cnf.bot.TOKEN}/{file_path}"

            print(f"✅ Сгенерирован URL: {direct_url}")

            return {
                "url": direct_url,
                "file_path": file_path,
                "status": "success"
            }

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return {"error": str(e), "status": "error"}



# --- 5. API: изменить статус заявки ---
@router.post("/status/update")
async def update_claim_status(data: dict):
    try:
        claim_id = data.get("claim_id")
        new_status = data.get("new_status")
        close_chat = data.get("close_chat", True)  # по умолчанию закрываем чат

        if not claim_id or not new_status:
            raise HTTPException(status_code=400, detail="claim_id and new_status required")

        # Находим заявку
        claim = await Claim.find_one({"claim_id": claim_id})
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")

        valid_statuses = ["pending", "confirm", "cancelled"]
        if new_status not in valid_statuses:
            raise HTTPException(status_code=400, detail="Invalid status")

        # Обновляем статус заявки
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


async def close_chat_session(claim_id: str):
    """Закрытие чат-сессии для заявки"""
    try:
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

            # Отправляем уведомление пользователю о закрытии чата
            await notify_user_about_chat_close(chat_session.user_id, claim_id)
        else:
            logger.info(f"ℹ️ Активная чат-сессия не найдена для заявки {claim_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка закрытия чат-сессии: {e}")


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
@router.get("/chat/photo/{message_id}")
async def get_chat_photo(message_id: str, admin=Depends(get_current_admin)):
    """Получить фото из сообщения чата"""
    # ПРАВИЛЬНЫЙ СИНТАКСИС
    message = await ChatMessage.find_one({"_id": message_id})  # ← словарь
    if not message or not message.has_photo or not message.photo_file_id:
        raise HTTPException(status_code=404, detail="Photo not found")

    try:
        file = await bot.get_file(message.photo_file_id)
        file_path = file.file_path
        file_bytes = await bot.download_file(file_path)

        return Response(
            content=file_bytes.getvalue(),
            media_type="image/jpeg",
            headers={"Content-Disposition": f"inline; filename=chat_photo_{message_id}.jpg"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading photo: {str(e)}")


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


@router.get("/chat/debug-all-messages")
async def debug_all_messages():
    """Показать все сообщения в базе для отладки"""
    messages = await ChatMessage.find_all().to_list()

    return {
        "total_messages": len(messages),
        "messages": [
            {
                "id": str(msg.id),
                "claim_id": msg.claim_id,
                "user_id": msg.user_id,
                "message": msg.message,
                "is_bot": msg.is_bot,
                "has_photo": msg.has_photo,
                "timestamp": msg.timestamp.isoformat()
            }
            for msg in messages
        ]
    }