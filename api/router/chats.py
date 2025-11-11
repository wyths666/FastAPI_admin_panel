from datetime import datetime, timezone
from typing import Optional
from fastapi import Request, Query, Depends, APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from beanie.operators import And, Or
from fastapi.templating import Jinja2Templates
from api.router.auth import get_current_admin
from core.bot1 import bot1
from db.beanie_bot1.models import Messages, Users
from utils.database import get_database_bot1

router = APIRouter()
templates = Jinja2Templates(directory="api/templates")
def build_pagination_url(page: int):
    return f"?page={page}"
templates.env.globals["build_pagination_url"] = build_pagination_url


@router.get("/chats/", response_class=HTMLResponse)
async def chats_page(
        request: Request,
        username: Optional[str] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        has_unread: Optional[bool] = Query(None),
        page: int = Query(1, ge=1),
        admin=Depends(get_current_admin)
):
    if not admin:
        return RedirectResponse("/auth/login")

    # Получаем прямое подключение к MongoDB
    db = get_database_bot1()
    messages_collection = db["messages"]
    users_collection = db["users"]

    # Параметры пагинации
    page_size = 50
    skip = (page - 1) * page_size

    # 1. Сначала получаем ID пользователей с сообщениями (с пагинацией)
    pipeline = [
        {"$group": {
            "_id": "$from_id",
            "last_message_date": {"$max": "$date"},
            "message_count": {"$sum": 1},
            "unread_count": {
                "$sum": {"$cond": [{"$eq": ["$checked", "0"]}, 1, 0]}
            }
        }},
        {"$sort": {"last_message_date": -1}}
    ]

    # Добавляем фильтры если есть
    match_stage = {}

    if date_from or date_to:
        date_filter = {}
        if date_from:
            try:
                date_filter["$gte"] = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        if date_to:
            try:
                dt_to = datetime.fromisoformat(date_to).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
                date_filter["$lte"] = dt_to
            except ValueError:
                pass
        if date_filter:
            match_stage["date"] = date_filter

    if match_stage:
        pipeline.insert(0, {"$match": match_stage})

    # Получаем общее количество чатов для пагинации
    count_pipeline = pipeline + [{"$count": "total"}]
    total_chats_result = await messages_collection.aggregate(count_pipeline).to_list()
    total_chats = total_chats_result[0]["total"] if total_chats_result else 0
    total_pages = (total_chats + page_size - 1) // page_size

    # Корректируем номер страницы
    if page > total_pages and total_pages > 0:
        page = total_pages
        skip = (page - 1) * page_size

    # Применяем пагинацию
    pipeline.extend([
        {"$skip": skip},
        {"$limit": page_size}
    ])

    # Выполняем агрегацию с пагинацией
    chats_aggregation = await messages_collection.aggregate(pipeline).to_list()

    # 2. Собираем данные для шаблона
    chats_data = []
    user_ids = [chat["_id"] for chat in chats_aggregation]

    if user_ids:
        # Получаем информацию о пользователях
        user_filter = {"id": {"$in": user_ids}}

        # Фильтр по username если указан
        if username and username.strip():
            user_filter["username"] = {"$regex": username.strip(), "$options": "i"}

        users_cursor = users_collection.find(user_filter)
        users_list = await users_cursor.to_list(length=None)
        users_dict = {user["id"]: user for user in users_list}
    else:
        users_dict = {}

    # 3. Обрабатываем каждый чат
    for chat in chats_aggregation:
        user_id = chat["_id"]
        user = users_dict.get(user_id)

        # Пропускаем если пользователь не найден или не подходит под фильтр username
        if not user:
            continue

        # Получаем последнее сообщение для превью
        last_message = await messages_collection.find_one(
            {"from_id": user_id},
            sort=[("date", -1)]
        )

        last_message_text = ""
        if last_message and last_message.get("message_object"):
            message_text = last_message["message_object"]
            last_message_text = message_text[:100] + "..." if len(message_text) > 100 else message_text

        chats_data.append({
            "user_id": user_id,
            "username": user.get("username", f"id{user_id}"),
            "full_name": user.get("full_name", "Неизвестный пользователь"),
            "banned": user.get("banned", "0"),
            "last_message_date": chat["last_message_date"],
            "message_count": chat["message_count"],
            "unread_count": chat["unread_count"],
            "last_message_preview": last_message_text or "(без текста)",
            "has_photo": last_message and last_message.get("file_type") == "photo" if last_message else False
        })

    # 4. Фильтр по непрочитанным (после пагинации)
    if has_unread:
        chats_data = [chat for chat in chats_data if chat["unread_count"] > 0]
        # Обновляем общее количество после фильтрации
        total_chats = len(chats_data)
        total_pages = (total_chats + page_size - 1) // page_size

    # 5. Рассчитываем диапазон отображаемых чатов
    start_chat = skip + 1
    end_chat = min(skip + len(chats_data), total_chats)

    return templates.TemplateResponse("chats.html", {
        "request": request,
        "chats": chats_data,
        "username": username,
        "date_from": date_from,
        "date_to": date_to,
        "has_unread": has_unread,
        "current_page": page,
        "total_pages": total_pages,
        "total_chats": total_chats,
        "start_chat": start_chat,
        "end_chat": end_chat
    })


@router.get("/chats/history/")
async def get_chat_history(
        user_id: int = Query(..., description="ID пользователя"),
        limit: int = Query(100, description="Лимит сообщений"),
        admin=Depends(get_current_admin)
):
    """Получить историю сообщений с пользователем"""
    if not admin:
        return {"error": "Unauthorized"}

    db = get_database_bot1()
    messages_collection = db["messages"]

    # Получаем сообщения напрямую из MongoDB
    messages_cursor = messages_collection.find(
        {"from_id": user_id}
    ).sort("date", -1).limit(limit)

    messages_list = await messages_cursor.to_list(length=None)

    # Преобразуем в нужный формат
    messages_data = []
    for msg in reversed(messages_list):
        messages_data.append({
            "id": str(msg["_id"]),  # ObjectId как строка
            "from_id": msg["from_id"],
            "message": msg.get("message_object", ""),
            "date": msg["date"],
            "file_id": msg.get("file_id", ""),
            "file_type": msg.get("file_type", "none"),
            "file_name": msg.get("file_name", ""),
            "file_size": msg.get("file_size", 0),
            "mime_type": msg.get("mime_type", ""),
            "from_operator": msg.get("from_operator", "0") == "1",
            "has_photo": msg.get("file_type") == "photo" and bool(msg.get("file_id")),
            "has_document": msg.get("file_type") == "document" and bool(msg.get("file_id")),
            "has_audio": msg.get("file_type") in ["audio", "voice"] and bool(msg.get("file_id")),
            "has_video": msg.get("file_type") in ["video", "video_note"] and bool(msg.get("file_id"))
        })

    return messages_data


@router.get("/chats/photo-url/{message_id}")
async def get_chat_photo_url(
        message_id: str,
        admin=Depends(get_current_admin)
):
    """
    Возвращает JSON с URL фото из Telegram CDN по message_id.
    """
    if not admin:
        return {"error": "Unauthorized"}

    try:
        db = get_database_bot1()
        messages_collection = db["messages"]

        # 1. Находим сообщение по _id
        from bson import ObjectId
        message = await messages_collection.find_one({"_id": ObjectId(message_id)})

        if not message or message.get("file_type") != "photo" or not message.get("file_id"):
            return {"error": "Photo not found"}

        # 2. Получаем file_path через Telegram API
        file = await bot1.get_file(message["file_id"])
        if not file.file_path:
            return {"error": "File path missing from Telegram"}

        # 3. Формируем публичный URL
        photo_url = f"https://api.telegram.org/file/bot{bot1.token}/{file.file_path}"

        return {"url": photo_url}

    except Exception as e:
        print(f"❌ Ошибка в /chats/photo-url/{message_id}: {e}")
        return {"error": f"Failed to get photo URL: {str(e)}"}


@router.get("/chats/download/{message_id}")
async def download_file(
        message_id: str,
        admin=Depends(get_current_admin)
):
    """Скачать файл"""
    if not admin:
        return {"error": "Unauthorized"}

    try:
        db = get_database_bot1()
        messages_collection = db["messages"]

        from bson import ObjectId
        message = await messages_collection.find_one({"_id": ObjectId(message_id)})

        if not message or not message.get("file_id"):
            return {"error": "File not found"}

        # Получаем файл через Telegram API
        file = await bot1.get_file(message["file_id"])

        # Скачиваем файл
        file_url = f"https://api.telegram.org/file/bot{bot1.token}/{file.file_path}"

        # Перенаправляем на прямой URL к файлу
        from fastapi.responses import RedirectResponse
        return RedirectResponse(file_url)

    except Exception as e:
        return {"error": str(e)}


@router.get("/chats/audio/{message_id}")
async def stream_audio(
        message_id: str,
        admin=Depends(get_current_admin)
):
    """Воспроизвести аудио"""
    # Аналогично download_file, но для аудио
    return await download_file(message_id, admin)


@router.get("/chats/video/{message_id}")
async def stream_video(
        message_id: str,
        admin=Depends(get_current_admin)
):
    """Воспроизвести видео"""
    # Аналогично download_file, но для видео
    return await download_file(message_id, admin)

@router.post("/chats/send/")
async def send_operator_message(
        data: dict,
        admin=Depends(get_current_admin)
):
    """Отправить сообщение от оператора и доставить пользователю в Telegram"""
    if not admin:
        return {"error": "Unauthorized"}

    user_id = data.get("user_id")
    text = data.get("text")

    if not user_id or not text:
        return {"error": "Missing user_id or text"}

    # Ограничиваем длину сообщения
    if len(text) > 4000:
        return {"error": "Сообщение слишком длинное (макс. 4000 символов)"}

    db = get_database_bot1()
    messages_collection = db["messages"]

    try:
        # 1. Проверяем, не заблокирован ли пользователь
        users_collection = db["users"]
        user = await users_collection.find_one({"id": user_id})

        if user and user.get("banned") == "1":
            return {"error": "Пользователь заблокирован"}

        # 2. Отправляем сообщение пользователю в Telegram
        telegram_success = await send_telegram_message(user_id, text)

        # 3. Получаем следующий ID сообщения
        last_message = await messages_collection.find_one({}, sort=[("id", -1)])
        next_id = last_message["id"] + 1 if last_message else 1

        # 4. Сохраняем сообщение в БД
        message_text = text
        if not telegram_success:
            message_text = text + " (не доставлено)"

        message_data = {
            "from_id": user_id,
            "message_object": message_text,
            "checked": "1",
            "date": datetime.now(timezone.utc),
            "file_id": "",
            "file_type": "text",
            "from_operator": "1",
            "id": next_id
        }

        await messages_collection.insert_one(message_data)

        return {
            "ok": True,
            "message_id": next_id,
            "delivered": telegram_success
        }

    except Exception as e:
        print(f"❌ Ошибка отправки сообщения: {e}")
        return {"error": f"Внутренняя ошибка: {str(e)}"}


async def send_telegram_message(user_id: int, text: str) -> bool:
    """Отправить сообщение пользователю через Telegram Bot API"""
    try:
        await bot1.send_message(
            chat_id=user_id,
            text=text
        )
        return True

    except Exception as e:
        print(f"❌ Ошибка отправки в Telegram пользователю {user_id}: {e}")
        return False

async def get_next_message_id() -> int:
    """Получить следующий ID для сообщения"""
    last_message = await Messages.find().sort("-id").limit(1).first_or_none()
    return last_message.id + 1 if last_message else 1


@router.post("/chats/user/ban")
async def ban_user_chat(
        data: dict,
        admin=Depends(get_current_admin)
):
    """Заблокировать пользователя в БД бота-1"""
    if not admin:
        return {"error": "Unauthorized"}

    user_id = data.get("user_id")
    if not user_id:
        return {"error": "Missing user_id"}

    db = get_database_bot1()
    users_collection = db["users"]

    try:
        result = await users_collection.update_one(
            {"id": user_id},
            {"$set": {"banned": "1"}}
        )

        if result.modified_count > 0:
            return {"ok": True, "message": f"Пользователь {user_id} заблокирован"}
        else:
            return {"ok": False, "error": "Пользователь не найден или уже заблокирован"}

    except Exception as e:
        return {"ok": False, "error": f"Ошибка базы данных: {str(e)}"}


@router.post("/chats/user/unban")
async def unban_user_chat(
        data: dict,
        admin=Depends(get_current_admin)
):
    """Разблокировать пользователя в БД бота-1"""
    if not admin:
        return {"error": "Unauthorized"}

    user_id = data.get("user_id")
    if not user_id:
        return {"error": "Missing user_id"}

    db = get_database_bot1()
    users_collection = db["users"]

    try:
        result = await users_collection.update_one(
            {"id": user_id},
            {"$set": {"banned": "0"}}
        )

        if result.modified_count > 0:
            return {"ok": True, "message": f"Пользователь {user_id} разблокирован"}
        else:
            return {"ok": False, "error": "Пользователь не найден или уже разблокирован"}

    except Exception as e:
        return {"ok": False, "error": f"Ошибка базы данных: {str(e)}"}


