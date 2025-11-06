# api/routers/bot2_claims.py
import datetime

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional


from api.router.auth import get_current_admin

from db.beanie.models.models import MOSCOW_TZ, ChatSession, Claim, ChatMessage

router = APIRouter(prefix="/bot2/claims")
templates = Jinja2Templates(directory="api/templates")


# Список заявок с фильтрацией
@router.get("/", response_class=HTMLResponse)
async def claims_list(
        request: Request,
        status: Optional[str] = Query(None),
        unanswered: Optional[bool] = Query(None),
        admin=Depends(get_current_admin)
):
    # Базовый запрос
    query = {}
    if status and status != "all":
        query["claim_status"] = status

    claims = await Claim.find(query).sort("-created_at").to_list()

    # Фильтрация по неотвеченным сообщениям
    if unanswered:
        claims_with_unanswered = []
        for claim in claims:
            chat_session = await ChatSession.find_one(
                {"claim_id": claim.claim_id, "is_active": True, "has_unanswered": True}
            )
            if chat_session:
                claims_with_unanswered.append({
                    "claim": claim,
                    "has_unanswered": True
                })
        claims_with_chat_status = claims_with_unanswered
    else:
        # Обычная проверка статуса чата
        claims_with_chat_status = []
        for claim in claims:
            chat_session = await ChatSession.find_one(
                {"claim_id": claim.claim_id, "is_active": True}
            )
            has_unanswered = chat_session.has_unanswered if chat_session else False

            claims_with_chat_status.append({
                "claim": claim,
                "has_unanswered": has_unanswered
            })

    # ПРАВИЛЬНЫЙ СИНТАКСИС ДЛЯ BEANIE COUNT
    status_counts = {
        "all": await Claim.count(),
        "pending": await Claim.find({"claim_status": "pending"}).count(),
        "confirm": await Claim.find({"claim_status": "confirm"}).count(),
        "cancelled": await Claim.find({"claim_status": "cancelled"}).count()
    }

    return templates.TemplateResponse(
        "bot2_claims.html",
        {
            "request": request,
            "admin": admin,
            "title": "Заявки на выплаты - Бот 2",
            "claims": claims_with_chat_status,
            "current_status": status,
            "status_counts": status_counts
        }
    )


# Детальная страница заявки
@router.get("/{claim_id}", response_class=HTMLResponse)
async def claim_detail(
        request: Request,
        claim_id: str,
        admin=Depends(get_current_admin)
):
    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        return HTMLResponse("Заявка не найдена", status_code=404)

    # Получаем или создаем чат-сессию
    chat_session = await ChatSession.find_one({"claim_id": claim_id})
    if not chat_session:
        chat_session = ChatSession(
            claim_id=claim_id,
            user_id=claim.user_id,
            admin_chat_id=admin.admin_id
        )
        await chat_session.insert()

    # История сообщений
    messages = await ChatMessage.find({"claim_id": claim_id}).sort("timestamp").to_list()

    # Список bank_member_id для выпадающего списка
    bank_members = ["Сбербанк", "Тинькофф", "ВТБ", "Альфа-Банк", "Газпромбанк"]

    return templates.TemplateResponse(
        "bot2_claim_detail.html",
        {
            "request": request,
            "admin": admin,
            "claim": claim,
            "chat_session": chat_session,
            "messages": messages,
            "bank_members": bank_members,
            "title": f"Заявка #{claim_id}"
        }
    )


# API для обновления статуса заявки
@router.post("/{claim_id}/update-status")
async def update_claim_status(
        claim_id: str,
        claim_status: str = Form(...),
        process_status: str = Form(...),
        bank_member_id: Optional[str] = Form(None),
        admin=Depends(get_current_admin)
):
    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        return JSONResponse({"error": "Заявка не найдена"}, status_code=404)

    update_data = {
        "claim_status": claim_status,
        "process_status": process_status,
        "updated_at": datetime.now(MOSCOW_TZ)
    }

    if bank_member_id:
        update_data["bank_member_id"] = bank_member_id

    await claim.update(**update_data)

    return {"status": "success", "message": "Статус обновлен"}


# API для отправки сообщения в чат
@router.post("/{claim_id}/chat/send")
async def send_chat_message(
        claim_id: str,
        message: str = Form(...),
        admin=Depends(get_current_admin)
):
    claim = await Claim.get(claim_id=claim_id)
    if not claim:
        return JSONResponse({"error": "Заявка не найдена"}, status_code=404)

    # Создаем сообщение от бота
    chat_message = ChatMessage(
        session_id=claim_id,  # используем claim_id как session_id для простоты
        claim_id=claim_id,
        user_id=claim.user_id,
        message=message,
        is_bot=True
    )
    await chat_message.insert()

    # Обновляем сессию чата
    chat_session = await ChatSession.find_one({"claim_id": claim_id})
    if chat_session:
        chat_session.has_unanswered = False  # сбрасываем флаг неотвеченных
        await chat_session.save()

    return {"status": "success", "message": "Сообщение отправлено"}


# API для получения истории чата
@router.get("/{claim_id}/chat/history")
async def get_chat_history(claim_id: str, admin=Depends(get_current_admin)):
    messages = await ChatMessage.find({"claim_id": claim_id}).sort("timestamp").to_list()
    return {"messages": messages}


# API для проверки новых сообщений
@router.get("/{claim_id}/chat/poll")
async def poll_chat_messages(
        claim_id: str,
        last_message_id: Optional[str] = Query(None),
        admin=Depends(get_current_admin)
):
    query = {"claim_id": claim_id, "is_bot": False}
    if last_message_id:
        # Здесь нужна логика для поиска сообщений после last_message_id
        pass

    new_messages = await ChatMessage.find(query).sort("-timestamp").limit(10).to_list()
    has_unanswered = len(new_messages) > 0

    # Обновляем флаг неотвеченных в сессии
    if has_unanswered:
        chat_session = await ChatSession.find_one({"claim_id": claim_id})
        if chat_session:
            chat_session.has_unanswered = True
            await chat_session.save()

    return {
        "has_new_messages": has_unanswered,
        "messages": new_messages
    }