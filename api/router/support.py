from aiogram.types import BufferedInputFile, InputFile
from beanie import PydanticObjectId
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from typing import Optional
from urllib.parse import quote
import httpx
from fastapi.responses import StreamingResponse
from bson import ObjectId
from bson.errors import InvalidId
import tempfile
import os
import mimetypes
from fastapi import HTTPException
from bot.templates.user import reg as treg
from bot.templates.user import menu as tmenu
from api.router.auth import get_current_admin
from core.bot import bot
from core.logger import api_logger as logger
from datetime import datetime
from fastapi.templating import Jinja2Templates
from db.beanie.models import SupportSession, SupportMessage, User
from utils.database import get_database

router = APIRouter(prefix="/support", tags=["support"])
templates = Jinja2Templates(directory="api/templates")


# Словарь состояний с русскими названиями
STATE_TRANSLATIONS = {
    "RegState:waiting_for_code": "⏳ Ожидание кода",
    "RegState:waiting_for_screenshot": "📸 Ожидание скриншота",
    "RegState:waiting_for_phone_or_card": "💳 Выбор способа оплаты",
    "RegState:waiting_for_bank": "🏦 Ожидание банка",
    "RegState:waiting_for_phone_number": "📱 Ожидание номера телефона",
    "RegState:waiting_for_card_number": "💳 Ожидание номера карты",
    "SupportState:waiting_for_message": "💬 Ожидание сообщения поддержки"
}

# Сообщения для каждого состояния (как в боте)
STATE_MESSAGES = {
    "RegState:waiting_for_code": "👋 Привет! Это бот компании Pure. Введите секретный код, указанный на голограмме.",
    "RegState:waiting_for_screenshot": treg.screenshot_request_text,
    "RegState:waiting_for_phone_or_card": treg.phone_or_card_text,
    "RegState:waiting_for_bank": treg.bank_request_text,
    "RegState:waiting_for_phone_number": treg.phone_format_text,
    "RegState:waiting_for_card_number": treg.card_format_text,
}

html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <script>
        alert("⚠️ Сессия уже закрыта. Действие недоступно.");
        window.location.href = "/support/";
    </script>
</head>
<body></body>
</html>
"""

def translate_state_value(key: str, value: any) -> str:
    """
    Переводит значения state_data на русский язык
    """
    if isinstance(value, bool):
        return "✅ Да" if value else "❌ Нет"

    elif key == "screenshot_received":
        return "✅ Получен" if value else "❌ Не получен"

    elif key == "photo_file_ids" and isinstance(value, list):
        return f"📷 {len(value)} фото"

    elif key in ["original_state", "state", "previous_state"] and isinstance(value, str):
        return STATE_TRANSLATIONS.get(value, value)

    elif key == "payment_method":
        payment_translations = {
            "card": "💳 Карта",
            "sbp": "📱 СБП"
        }
        return payment_translations.get(value, str(value))

    elif isinstance(value, str) and value.startswith(('RegState:', 'SupportState:')):
        return STATE_TRANSLATIONS.get(value, value)

    else:
        return str(value)


@router.get("/", response_class=HTMLResponse)
async def support_dashboard(request: Request, resolved: bool = False, admin=Depends(get_current_admin)):
    """Главная страница техподдержки со списком сессий"""
    if not admin:
        return RedirectResponse("/auth/login")

    # Базовый запрос
    query = {"resolved": resolved}

    # Получаем ВСЕ сессии без пагинации
    sessions = await SupportSession.find(query).sort("-created_at").to_list()

    # Получаем общее количество
    total_sessions = len(sessions)

    # Собираем ID пользователей для запроса
    user_ids = [session.user_id for session in sessions]

    # Получаем информацию о пользователях
    users = await User.find({"tg_id": {"$in": user_ids}}).to_list()
    users_map = {user.tg_id: user for user in users}

    STATE_DATA_TRANSLATIONS = {
        "claim_id": "ID заявки",
        "entered_code": "Введенный код",
        "photo_file_ids": "ID фото",
        "review_text": "Текст отзыва",
        "screenshot_received": "Скриншот получен",
        "phone_card_message_id": "ID сообщения выбора оплаты",
        "payment_method": "Способ оплаты",
        "phone_number": "Номер телефона",
        "bank": "Банк",
        "card_number": "Номер карты",
        "card": "Номер карты",
        "original_state": "Исходное состояние",
        "original_data": "Исходные данные"
    }
    # Форматируем данные для шаблона
    sessions_with_users = []
    for session in sessions:
        session_dict = session.dict()
        session_dict["id"] = str(session.id)

        # Получаем данные пользователя
        user = users_map.get(session.user_id)
        if user:
            session_dict["username"] = user.username or f"user_{user.tg_id}"
            session_dict["first_name"] = getattr(user, 'first_name', None)
            session_dict["last_name"] = getattr(user, 'last_name', None)
            session_dict["banned"] = user.banned
            session_dict["user_created_at"] = user.created_at
        else:
            # Если пользователь не найден в базе
            session_dict["username"] = f"user_{session.user_id}"
            session_dict["first_name"] = None
            session_dict["last_name"] = None
            session_dict["banned"] = False
            session_dict["user_created_at"] = None

        # Форматируем state для отображения
        if session.state:
            session_dict["state_display"] = STATE_TRANSLATIONS.get(
                session.state,
                session.state.replace('_', ' ').title()
            )
        else:
            session_dict["state_display"] = "Не указано"

        if session.previous_state:
            session_dict["previous_state_display"] = STATE_TRANSLATIONS.get(
                session.previous_state,
                session.previous_state.replace('_', ' ').title()
            )
        if session.state_data:
            preview_data = {}

            for key, value in session.state_data.items():
                if isinstance(value, (dict, list)) and not (key == "photo_file_ids" and isinstance(value, list)):
                    continue

                translated_key = STATE_DATA_TRANSLATIONS.get(key, key)
                formatted_value = translate_state_value(key, value)

                if formatted_value and formatted_value not in ['', 'None', '[]', '{}'] and len(formatted_value) < 100:
                    preview_data[translated_key] = formatted_value

            session_dict["state_data_preview"] = preview_data
        else:
            session_dict["state_data_preview"] = {}

        sessions_with_users.append(session_dict)

    return templates.TemplateResponse(
        "support.html",
        {
            "request": request,
            "sessions": sessions_with_users,
            "active_tab": "resolved" if resolved else "active",
            "total_sessions": total_sessions

        }
    )

@router.get("/api/session/{session_id}/messages")
async def get_session_messages_api(session_id: str):
    """API для получения сообщений сессии"""
    session = await SupportSession.get(session_id)
    if not session:
        return []

    messages = await SupportMessage.find(
        {"session_id": session.id}
    ).sort("timestamp").to_list()

    return [
        {
            **message.dict(),
            "id": str(message.id)
        }
        for message in messages
    ]


@router.get("/session/{session_id}", response_class=HTMLResponse)
async def support_session_detail(request: Request, session_id: str):
    """Детальная страница сессии поддержки с чатом"""
    session = await SupportSession.get(session_id)
    if not session:
        return RedirectResponse("/support/")

    # Получаем сообщения сессии
    messages = await SupportMessage.find(
        {"session_id": session.id}
    ).sort("timestamp").to_list()

    # Словарь для перевода ключей state_data
    STATE_DATA_TRANSLATIONS = {
        "claim_id": "ID заявки",
        "entered_code": "Введенный код",
        "photo_file_ids": "ID фото",
        "review_text": "Текст отзыва",
        "screenshot_received": "Скриншот получен",
        "phone_card_message_id": "ID сообщения выбора оплаты",
        "payment_method": "Способ оплаты",
        "phone_number": "Номер телефона",
        "bank": "Банк",
        "card_number": "Номер карты",
        "original_state": "Исходное состояние",
        "original_data": "Исходные данные"
    }

    # Форматируем данные для шаблона
    session_data = session.dict()
    session_data["id"] = str(session.id)

    # Переводим состояние
    if session_data["state"]:
        session_data["state_display"] = STATE_TRANSLATIONS.get(
            session_data["state"],
            session_data["state"].replace('_', ' ').title()
        )
    else:
        session_data["state_display"] = "Не указано"

    # Переводим предыдущее состояние если есть

    if session_data.get("previous_state"):
        session_data["previous_state_display"] = STATE_TRANSLATIONS.get(
            session_data["previous_state"],
            session_data["previous_state"].replace('_', ' ').title()
        )

    # Форматируем state_data с переводами

    if session_data.get("state_data"):
        translated_state_data = {}
        for key, value in session_data["state_data"].items():
            translated_key = STATE_DATA_TRANSLATIONS.get(key, key)
            # Форматируем значения
            if isinstance(value, bool):
                formatted_value = "✅ Да" if value else "❌ Нет"
            elif key == "screenshot_received":
                formatted_value = "✅ Получен" if value else "❌ Не получен"
            elif key == "photo_file_ids" and isinstance(value, list):
                formatted_value = f"📷 {len(value)} фото"
            elif isinstance(value, dict):
                formatted_value = str(value)  # Для сложных объектов просто строку
            else:
                formatted_value = str(value)

            translated_state_data[translated_key] = formatted_value

        session_data["state_data_preview"] = translated_state_data
    else:
        session_data["state_data_preview"] = {}

    messages_data = []
    for msg in messages:
        msg_dict = msg.dict()
        msg_dict["id"] = str(msg.id)
        messages_data.append(msg_dict)

    return templates.TemplateResponse(
        "support.html",
        {
            "request": request,
            "session": session_data,
            "messages": messages_data
        }
    )

@router.post("/session/{session_id}/send_message")
async def send_text_message(
        request: Request,
        session_id: str,
        message: str = Form(...)
):
    """Отправка текстового сообщения пользователю через бота"""
    try:
        # Получаем сессию поддержки
        session = await SupportSession.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")

        if session.resolved:
            raise HTTPException(status_code=400, detail="Сессия уже закрыта")

        # Получаем информацию о пользователе
        user = await User.find_one({"tg_id": session.user_id})
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        if user.banned:
            raise HTTPException(status_code=400, detail="Пользователь заблокирован")

        text = message.strip()

        if not text:
            raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

        # Отправляем текстовое сообщение
        try:
            await bot.send_message(
                chat_id=session.user_id,
                text=text
            )
            logger.info(f"💬 [SupportSend] Отправлен текст пользователю {session.user_id}: '{text}'")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки текста: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Ошибка отправки текста: {str(e)}")

        # Сохраняем сообщение в базу - ВАЖНО: is_bot=True для сообщений от админа
        support_message = SupportMessage(
            session_id=session.id,
            user_id=session.user_id,
            message=text,
            is_bot=True,  # Сообщение от админа (бота)
            has_photo=False,
            has_document=False,
            timestamp=datetime.now()
        )

        await support_message.create()
        logger.info(f"✅ [SupportSend] Текстовое сообщение сохранено в сессию {session_id}")

        return {"status": "success", "message": "Сообщение отправлено"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [SupportSend] Неожиданная ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")


@router.post("/session/{session_id}/send_file")
async def send_support_file(
    session_id: str,
    file: UploadFile = File(...),
    caption: str = Form(""),

):
    try:
        try:
            obj_id = PydanticObjectId(session_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Некорректный session_id")

        session = await SupportSession.get(obj_id)
        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")
        if session.resolved:
            raise HTTPException(status_code=400, detail="Сессия уже закрыта")

        user = await User.find_one(User.tg_id == session.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        if user.banned:
            raise HTTPException(status_code=400, detail="Пользователь заблокирован")

        contents = await file.read()
        size = len(contents)

        if size == 0:
            raise HTTPException(status_code=400, detail="Файл пустой")
        if size > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 50 МБ)")

        filename = file.filename or "file"
        mime_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        input_file = BufferedInputFile(contents, filename=filename)
        safe_caption = (caption[:1024] or "").strip()

        is_photo = mime_type.startswith("image/") and not mime_type.endswith("svg+xml")
        file_id = None

        try:
            if is_photo:
                msg = await bot.send_photo(
                    chat_id=session.user_id,
                    photo=input_file,
                    caption=safe_caption or None,
                )
                file_id = msg.photo[-1].file_id if msg.photo else None
            else:
                msg = await bot.send_document(
                    chat_id=session.user_id,
                    document=input_file,
                    caption=safe_caption or None,
                )
                file_id = msg.document.file_id if msg.document else None

            if not file_id:
                logger.warning("⚠️ Telegram вернул сообщение без file_id")
                safe_caption += " (не доставлено)"

        except Exception as e:
            logger.error(f"❌ Telegram send failed for session {session_id}: {e}")
            safe_caption += " (ошибка отправки)"

        new_message = SupportMessage(
            session_id=obj_id,
            user_id=session.user_id,
            message=safe_caption or filename,
            is_bot=True,
            has_photo=is_photo,
            photo_file_id=file_id if is_photo else None,
            photo_caption=safe_caption if is_photo else None,
            has_document=not is_photo,
            document_file_id=file_id if not is_photo else None,
            document_name=filename,
            document_mime_type=mime_type,
            document_size=size,
            timestamp=datetime.now(),
        )

        await new_message.insert()

        logger.info(
            f"✅ Файл {'фото' if is_photo else 'документ'} "
            f"ID={new_message.id} сохранён в сессию {session_id}"
        )

        return JSONResponse({
            "status": "success",
            "message_id": str(new_message.id),
            "file_type": "photo" if is_photo else "document",
            "delivered": bool(file_id),
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"💥 Fatal error in /session/{session_id}/send_file: {e}")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")


@router.get("/session/{session_id}/photo/{photo_file_id}")
async def get_support_photo(session_id: str, photo_file_id: str):
    """Получение фото из чата поддержки"""
    try:
        # Проверяем существование сессии
        session = await SupportSession.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")

        # Проверяем существование сообщения с фото
        message = await SupportMessage.find_one({
            "session_id": session.id,
            "photo_file_id": photo_file_id,
            "has_photo": True
        })

        if not message:
            raise HTTPException(status_code=404, detail="Фото не найдено")

        # Получаем файл от Telegram
        try:
            file = await bot.get_file(photo_file_id)
            file_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"

            # Перенаправляем на файл Telegram
            return RedirectResponse(file_url)

        except Exception as e:
            logger.error(f"❌ Ошибка получения фото: {str(e)}")
            raise HTTPException(status_code=404, detail="Фото не доступно")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка получения фото: {str(e)}")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")



@router.get("/session/{session_id}/document/{document_file_id}")
async def download_support_document(
    session_id: str,
    document_file_id: str,

):
    """Скачивание документа из чата поддержки (Streaming, безопасно, как в download_chat_file)"""
    try:
        # 1. Валидация и получение сессии
        try:
            session_oid = ObjectId(session_id)
        except (InvalidId, TypeError):
            raise HTTPException(status_code=400, detail="Некорректный ID сессии")

        session = await SupportSession.get(session_oid)
        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")

        # 2. Получаем сообщение с документом
        message = await SupportMessage.find_one({
            "session_id": session_oid,
            "document_file_id": document_file_id,
            "has_document": True
        })
        if not message:
            raise HTTPException(status_code=404, detail="Документ не найден")

        # 3. Получаем file_info от Telegram
        try:
            file_info = await bot.get_file(document_file_id)
        except Exception as e:
            logger.error(f"Telegram get_file failed for {document_file_id}: {e}")
            raise HTTPException(status_code=404, detail="Не удалось получить метаданные файла")

        if not file_info.file_path:
            raise HTTPException(status_code=500, detail="File path отсутствует в ответе Telegram")

        file_url = f"https://api.telegram.org/file/bot{bot.token}/{file_info.file_path}"

        # 4. Скачиваем через httpx (асинхронно + streaming)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(file_url)
            if resp.status_code != 200:
                logger.error(f"HTTP {resp.status_code} при скачивании {file_url}")
                raise HTTPException(status_code=502, detail="Не удалось загрузить файл с сервера Telegram")

            # 5. Определяем имя файла
            filename = message.document_name or "document"

            # Если имя "без расширения", но известен MIME — добавим
            content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()

            ext_map = {
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
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "audio/mpeg": ".mp3",
                "audio/wav": ".wav",
                "video/mp4": ".mp4",
            }

            # Добавляем расширение, если его нет и мы можем определить по MIME
            ext = ext_map.get(content_type, "")
            clean_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in filename).strip()
            if not clean_name:
                clean_name = "document"

            if ext and not clean_name.lower().endswith(tuple(ext_map.values())):
                clean_name += ext

            # 6. Формируем заголовки
            headers = {
                "Content-Type": content_type,
                "Content-Disposition": f'attachment; filename="{quote(clean_name)}"',
                "Cache-Control": "private, max-age=300",
            }

            # 7. StreamingResponse (потоковая отдача — память не растёт)
            async def file_stream():
                async for chunk in resp.aiter_bytes(65536):
                    yield chunk

            return StreamingResponse(file_stream(), headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ download_support_document({session_id}, {document_file_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")


@router.post("/session/{session_id}/resolve")
async def resolve_session(
        request: Request,
        session_id: str
):
    """Закрытие обращения с отправкой уведомления пользователю и сброс состояния"""
    try:
        # Для Beanie
        session = await SupportSession.find_one(SupportSession.id == PydanticObjectId(session_id))

        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")

        if session.resolved:
            return HTMLResponse(content=html_content, status_code=200)

        # Получаем информацию о пользователе
        user = await User.find_one(User.tg_id == session.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # Сбрасываем состояние пользователя в FSM
        mongo_db = get_database()
        fsm_key = f"fsm:{session.user_id}:{session.user_id}"

        # Получаем текущее состояние для сохранения в истории
        current_fsm_data = await mongo_db.aiogram_fsm_states.find_one({"_id": fsm_key})

        if current_fsm_data:
            # Сохраняем предыдущее состояние в сессии поддержки
            session.previous_state = current_fsm_data.get("state")
            session.previous_state_data = current_fsm_data.get("data", {})

            # Полностью очищаем состояние пользователя
            await mongo_db.aiogram_fsm_states.delete_one({"_id": fsm_key})
            logger.info(f"🔄 [SupportClose] Состояние пользователя {session.user_id} сброшено")
        else:
            logger.warning(f"⚠️ [SupportClose] Не найдено FSM состояние для пользователя {session.user_id}")

        # Отправляем сообщение пользователю о закрытии обращения
        try:
            await bot.send_message(
                chat_id=session.user_id,
                text="✅ Ваше обращение в техническую поддержку закрыто. Если у вас возникнут новые вопросы, создайте новое обращение."

            )
            logger.info(f"📨 [SupportClose] Отправлено уведомление о закрытии пользователю {session.user_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления о закрытии: {str(e)}")

        # Закрываем сессию
        session.resolved = True
        session.resolved_by_admin_id = 1
        await session.save()

        logger.info(f"✅ [SupportClose] Сессия {session_id} закрыта, состояние пользователя сброшено")

        return RedirectResponse("/support/", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [SupportClose] Ошибка закрытия сессии: {str(e)}")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")


async def clean_and_set_state(user_id: int, target_state: str, session_data: dict = None):
    """
    Очищает текущее состояние и устанавливает новое чистое состояние
    """
    mongo_db = get_database()
    fsm_key = f"fsm:{user_id}:{user_id}"

    # Базовые данные для нового состояния
    base_data = {
        "clean_start": True,
        "session_timestamp": datetime.now().isoformat()
    }

    # Добавляем данные сессии если есть
    if session_data:
        base_data.update(session_data)

    # Устанавливаем новое состояние с очищенными данными
    await mongo_db.aiogram_fsm_states.update_one(
        {"_id": fsm_key},
        {
            "$set": {
                "state": target_state,
                "data": base_data
            }
        },
        upsert=True
    )

    logger.info(f"✅ [CleanState] Пользователь {user_id} переведен в состояние {target_state}")
    return base_data


@router.post("/session/{session_id}/rollback")
async def rollback_session_state(
        session_id: str,
        target_state: str = Form(...),
        admin=Depends(get_current_admin)
):
    """Откат состояния сессии на выбранный шаг"""
    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        logger.info(f"🔍 [Rollback] Начало отката сессии {session_id} для target_state={target_state}")

        # Получаем сессию
        session = await SupportSession.find_one({"_id": PydanticObjectId(session_id)})
        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")

        if session.resolved:
            return HTMLResponse(content=html_content, status_code=200)

        # Получаем пользователя
        user = await User.find_one({"tg_id": session.user_id})
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # Используем глобальную get_database()
        mongo_db = get_database()

        # Получаем текущее FSM состояние пользователя из MongoDB
        fsm_key = f"fsm:{session.user_id}:{session.user_id}"
        logger.info(f"🔍 [Rollback] Поиск FSM данных по ключу: {fsm_key}")
        fsm_data = await mongo_db.aiogram_fsm_states.find_one({"_id": fsm_key})

        # Данные из сессии поддержки (это snapshot на момент входа в поддержку)
        session_state = session.state
        session_data = session.state_data or {}

        logger.info(f"🔍 [Rollback] State из сессии: {session_state}")
        logger.info(f"🔍 [Rollback] Data из сессии: {session_data}")

        # Получаем доступные для отката состояния
        available_states_dict = get_available_rollback_states_from_session(session_state)

        logger.info(f"🔍 [Rollback] Доступные состояния: {available_states_dict}")

        # Проверяем, что целевое состояние доступно
        if target_state not in available_states_dict:
            raise HTTPException(
                status_code=400,
                detail=f"Невозможно вернуться к состоянию '{target_state}'. Доступные варианты: {', '.join([f'{k} ({v})' for k, v in available_states_dict.items()])}"
            )

        logger.info(f"🔍 [Rollback] Целевое состояние подтверждено: {target_state}")

        # Подготавливаем новые данные для целевого состояния
        # Основные данные берем из session_data (это original_data из хендлера)
        new_fsm_data = {}

        if target_state == "RegState:waiting_for_code":
            new_fsm_data = {
                "claim_id": session_data.get("claim_id"),
                "entered_code": session_data.get("entered_code"),
                "support_session_id": str(session.id),
                "support_session_closed": True
            }
        elif target_state == "RegState:waiting_for_screenshot":
            new_fsm_data = {
                "claim_id": session_data.get("claim_id"),
                "entered_code": session_data.get("entered_code"),
                "support_session_id": str(session.id),
                "support_session_closed": True
            }
        elif target_state == "RegState:waiting_for_phone_or_card":
            new_fsm_data = {
                "claim_id": session_data.get("claim_id"),
                "entered_code": session_data.get("entered_code"),
                "photo_file_ids": session_data.get("photo_file_ids", []),
                "review_text": session_data.get("review_text", ""),
                "screenshot_received": True,
                "support_session_id": str(session.id),
                "support_session_closed": True
            }
        elif target_state == "RegState:waiting_for_phone_number":
            new_fsm_data = {
                "claim_id": session_data.get("claim_id"),
                "entered_code": session_data.get("entered_code"),
                "photo_file_ids": session_data.get("photo_file_ids", []),
                "review_text": session_data.get("review_text", ""),
                "screenshot_received": True,
                "support_session_id": str(session.id),
                "support_session_closed": True
            }
        elif target_state == "RegState:waiting_for_card_number":
            new_fsm_data = {
                "claim_id": session_data.get("claim_id"),
                "entered_code": session_data.get("entered_code"),
                "photo_file_ids": session_data.get("photo_file_ids", []),
                "review_text": session_data.get("review_text", ""),
                "screenshot_received": True,
                "phone_card_message_id": session_data.get("phone_card_message_id"),
                "support_session_id": str(session.id),
                "support_session_closed": True
            }
        elif target_state == "RegState:waiting_for_bank":
            new_fsm_data = {
                "claim_id": session_data.get("claim_id"),
                "entered_code": session_data.get("entered_code"),
                "photo_file_ids": session_data.get("photo_file_ids", []),
                "review_text": session_data.get("review_text", ""),
                "screenshot_received": True,
                "phone_card_message_id": session_data.get("phone_card_message_id"),
                "support_session_id": str(session.id),
                "support_session_closed": True
            }
        else:
            new_fsm_data = {
                "support_session_id": str(session.id),
                "support_session_closed": True
            }

        logger.info(f"🔍 [Rollback] Новые данные FSM: {new_fsm_data}")

        # Обновляем FSM в MongoDB (СБРАСЫВАЕМ состояние и устанавливаем новое)
        update_result = await mongo_db.aiogram_fsm_states.update_one(
            {"_id": fsm_key},
            {
                "$set": {
                    "state": target_state,
                    "data": new_fsm_data
                }
            },
            upsert=True  # Создаем если не существует
        )

        logger.info(f"✅ [Rollback] FSM обновлен. Изменено документов: {update_result.modified_count}")

        # Отправляем сообщение пользователю
        message_text = STATE_MESSAGES.get(target_state, "🔄 Состояние обновлено. Продолжайте оформление заявки.")

        try:
            if target_state == "RegState:waiting_for_phone_or_card":
                await bot.send_message(
                    chat_id=session.user_id,
                    text=f"🔄 Ваше обращение в поддержку завершено.\n {message_text}",
                    reply_markup=tmenu.phone_or_card_ikb()
                )
            else:
                await bot.send_message(
                    chat_id=session.user_id,
                    text=f"🔄 Ваше обращение в поддержку завершено.\n {message_text}"
                )
            logger.info(f"✅ [Rollback] Сообщение отправлено пользователю {session.user_id}")
        except Exception as e:
            logger.error(f"⚠️ [Rollback] Ошибка отправки сообщения: {str(e)}")

        # Закрываем сессию поддержки
        session.resolved = True
        session.resolved_by_admin_id = 1
        session.previous_state = session.state
        session.previous_state_data = session.state_data
        session.rollback_count = (session.rollback_count or 0) + 1

        await session.save()
        logger.info(f"✅ [Rollback] Сессия {session_id} закрыта")

        return RedirectResponse("/support/", status_code=303)

    except HTTPException as he:
        logger.error(f"❌ [Rollback] HTTP ошибка: {he.detail}")
        raise he
    except Exception as e:
        logger.error(f"❌ [Rollback] Неожиданная ошибка: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


@router.get("/session/{session_id}/available_rollback_states")
async def get_available_rollback_states_api(session_id: str):
    """Возвращает доступные для отката состояния для фронтенда"""
    try:
        session = await SupportSession.find_one(SupportSession.id == PydanticObjectId(session_id))
        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")

        # Используем состояние из сессии поддержки
        current_state = session.state
        logger.info(f"🔍 [AvailableStates] Текущее состояние из сессии: {current_state}")

        available_states = get_available_rollback_states_from_session(current_state)
        return {"available_states": available_states}

    except Exception as e:
        logger.error(f"❌ Ошибка получения доступных состояний: {str(e)}")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")


def get_available_rollback_states_from_session(current_state: str) -> dict:
    """
    Возвращает доступные для отката состояния на основе текущего состояния из сессии
    """
    logger.info(f"🔍 [RollbackFromSession] Текущее состояние: {current_state}")

    # Явное определение доступных состояний для каждого текущего состояния
    AVAILABLE_FOR_STATE = {
        # Начальные состояния
        "RegState:waiting_for_code": {
            # Можно вернуть только к началу (нет предыдущих состояний)
        },

        "RegState:waiting_for_screenshot": {
            "RegState:waiting_for_screenshot": "📸 Ожидание скриншота"
        },

        "RegState:waiting_for_phone_or_card": {
            "RegState:waiting_for_screenshot": "📸 Ожидание скриншота"
        },

        # Состояния после выбора карты
        "RegState:waiting_for_card_number": {
            "RegState:waiting_for_screenshot": "📸 Ожидание скриншота",
            "RegState:waiting_for_phone_or_card": "💳 Выбор способа оплаты"
        },

        # Состояния после выбора СБП
        "RegState:waiting_for_phone_number": {
            "RegState:waiting_for_screenshot": "📸 Ожидание скриншота",
            "RegState:waiting_for_phone_or_card": "💳 Выбор способа оплаты"
        },

        "RegState:waiting_for_bank": {
            "RegState:waiting_for_screenshot": "📸 Ожидание скриншота",
            "RegState:waiting_for_phone_or_card": "💳 Выбор способа оплаты",
            "RegState:waiting_for_phone_number": "📱 Ожидание номера телефона"
        }
    }

    available_states = AVAILABLE_FOR_STATE.get(current_state, {})
    logger.info(f"🔍 [RollbackFromSession] Доступные состояния: {list(available_states.keys())}")
    return available_states


@router.post("/session/{session_id}/block_user")
async def block_user(request: Request, session_id: str):
    """Блокировка/разблокировка пользователя из сессии поддержки"""
    try:
        # Получаем сессию поддержки
        session = await SupportSession.find_one(SupportSession.id == PydanticObjectId(session_id))
        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")

        if session.resolved:
            return HTMLResponse(content=html_content, status_code=200)

        # Получаем пользователя
        user = await User.find_one(User.tg_id == session.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # Определяем новое состояние
        new_banned_status = not user.banned

        await user.update(banned=new_banned_status)

        action = "разблокирован" if not new_banned_status else "заблокирован"
        logger.warning(f"🔒 [Support] Пользователь {action} {session.user_id} (сессия: {session_id})")

        return RedirectResponse(f"/support/", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [SupportBlock] Ошибка блокировки пользователя: {str(e)}")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")


@router.get("/api/sessions")
async def get_sessions_api(resolved: bool = False):
    """API для получения списка сессий"""
    sessions = await SupportSession.find({"resolved": resolved}).sort("-created_at").to_list()
    return [
        {
            **session.dict(),
            "id": str(session.id),
            "username": f"user_{session.user_id}"  # Заменить на реальный username
        }
        for session in sessions
    ]


