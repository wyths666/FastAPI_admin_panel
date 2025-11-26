from fastapi.responses import StreamingResponse
import httpx
from typing import Union
from fastapi import Query, HTTPException, Request, Depends
import mimetypes
from urllib.parse import quote
from datetime import datetime, timezone
from typing import Optional
from fastapi import Request, Query, Depends, APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from api.router.auth import get_current_admin
from core.bot1 import bot1
from db.beanie_bot1.models import Messages, Users
from utils.database import get_database_bot1
from fastapi.responses import JSONResponse
from core.logger import api_logger as logger

router = APIRouter()
templates = Jinja2Templates(directory="api/templates")
def build_pagination_url(page: int):
    return f"?page={page}"
templates.env.globals["build_pagination_url"] = build_pagination_url



@router.get("/chats/", response_class=HTMLResponse)
async def chats_page(
    request: Request,
    username: Optional[str] = Query(None),
    user_id: Union[str, None] = Query(None),  # ← принимаем как строку
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    has_unread: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    admin=Depends(get_current_admin)
):
    if not admin:
        return RedirectResponse("/auth/login")

    # Безопасное преобразование user_id → int | None
    filter_user_id: Optional[int] = None
    if user_id is not None and user_id.strip() != "":
        try:
            filter_user_id = int(user_id.strip())
        except (ValueError, TypeError):
            # Опционально: можно вернуть ошибку или игнорировать
            # Например, игнорируем и не фильтруем по user_id
            pass

    # Подключение к БД
    db = get_database_bot1()
    messages_collection = db["messages"]
    users_collection = db["users"]

    page_size = 50
    skip = (page - 1) * page_size

    # Агрегация
    pipeline = [
        {"$group": {
            "_id": "$from_id",
            "last_message_date": {"$max": "$date"},
            "message_count": {"$sum": 1},
            "unread_count": {
                "$sum": {
                    "$cond": [
                        {
                            "$and": [
                                {"$eq": ["$checked", "0"]},
                                {"$eq": ["$from_operator", "0"]}
                            ]
                        },
                        1,
                        0
                    ]
                }
            }
        }},
        {"$sort": {"last_message_date": -1}}
    ]

    match_stage = {}

    # Фильтр по user_id (уже int или None)
    if filter_user_id is not None:
        match_stage["from_id"] = filter_user_id

    # Фильтр по дате
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

    # Подсчёт общего числа
    count_pipeline = pipeline + [{"$count": "total"}]
    total_chats_result = await messages_collection.aggregate(count_pipeline).to_list(length=None)
    total_chats = total_chats_result[0]["total"] if total_chats_result else 0
    total_pages = (total_chats + page_size - 1) // page_size

    if page > total_pages and total_pages > 0:
        page = total_pages
        skip = (page - 1) * page_size

    pipeline.extend([
        {"$skip": skip},
        {"$limit": page_size}
    ])

    chats_aggregation = await messages_collection.aggregate(pipeline).to_list(length=None)

    # Получение пользователей
    chats_data = []
    chat_user_ids = [chat["_id"] for chat in chats_aggregation]

    users_dict = {}
    if chat_user_ids:
        user_filter = {"id": {"$in": chat_user_ids}}
        if username and username.strip():
            user_filter["username"] = {"$regex": username.strip(), "$options": "i"}

        users_list = await users_collection.find(user_filter).to_list(length=None)
        users_dict = {u["id"]: u for u in users_list}

    # Формирование данных
    for chat in chats_aggregation:
        chat_user_id = chat["_id"]
        user = users_dict.get(chat_user_id)
        if not user:
            continue

        last_message = await messages_collection.find_one(
            {"from_id": chat_user_id},
            sort=[("date", -1)]
        )

        last_message_text = ""
        has_photo = False
        if last_message:
            msg_obj = last_message.get("message_object", "")
            last_message_text = (msg_obj[:100] + "..." if len(msg_obj) > 100 else msg_obj) or "(без текста)"
            has_photo = last_message.get("file_type") == "photo"

        chats_data.append({
            "user_id": chat_user_id,
            "username": user.get("username", f"id{chat_user_id}"),
            "full_name": user.get("full_name", "Неизвестный пользователь"),
            "banned": user.get("banned", "0"),
            "last_message_date": chat["last_message_date"],
            "message_count": chat["message_count"],
            "unread_count": chat["unread_count"],
            "last_message_preview": last_message_text,
            "has_photo": has_photo
        })

    # Фильтр по непрочитанным
    if has_unread is True:
        chats_data = [c for c in chats_data if c["unread_count"] > 0]
        total_chats = len(chats_data)
        total_pages = (total_chats + page_size - 1) // page_size

    start_chat = skip + 1
    end_chat = min(skip + len(chats_data), total_chats)

    return templates.TemplateResponse("chats.html", {
        "request": request,
        "chats": chats_data,
        "username": username,
        "user_id": filter_user_id,  # ← int или None (безопасно)
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

    # 1. СНАЧАЛА загружаем сообщения
    messages_cursor = messages_collection.find(
        {"from_id": user_id}
    ).sort("date", -1).limit(limit)

    messages_list = await messages_cursor.to_list(length=None)

    # 2. ПОТОМ помечаем как прочитанные
    unread_count = await messages_collection.count_documents({
        "from_id": user_id,
        "from_operator": "0",
        "checked": "0"
    })

    if unread_count > 0:
        await messages_collection.update_many(
            {
                "from_id": user_id,
                "from_operator": "0",
                "checked": "0"
            },
            {
                "$set": {"checked": "1"}
            }
        )

    # 3. Преобразуем в нужный формат
    messages_data = []
    for msg in reversed(messages_list):
        messages_data.append({
            "id": str(msg["_id"]),
            "from_id": msg["from_id"],
            "message": msg.get("message_object", ""),
            "date": msg["date"],
            "file_id": msg.get("file_id", ""),
            "file_type": msg.get("file_type", "none"),
            "from_operator": msg.get("from_operator", "0") == "1",
            "checked": msg.get("checked", "0") == "1",  # ← ДОБАВЛЕНО ДЛЯ НЕПРОЧИТАННЫХ
            "has_photo": msg.get("file_type") == "photo" and bool(msg.get("file_id")),
            # Дополнительные поля для файлов
            "file_name": msg.get("file_name", ""),
            "file_size": msg.get("file_size", 0),
            "mime_type": msg.get("mime_type", ""),
            "has_document": msg.get("file_type") == "document" and bool(msg.get("file_id")),
            "has_audio": msg.get("file_type") in ["audio", "voice"] and bool(msg.get("file_id")),
            "has_video": msg.get("file_type") in ["video", "video_note"] and bool(msg.get("file_id"))
        })

    return messages_data


# @router.get("/chats/photo/{message_id}")
# async def get_chat_photo_proxy(
#         message_id: str,
#         admin=Depends(get_current_admin)
# ):
#     """Proxy для отображения фото"""
#     if not admin:
#         return {"error": "Unauthorized"}
#
#     try:
#         db = get_database_bot1()
#         messages_collection = db["messages"]
#
#         from bson import ObjectId
#         message = await messages_collection.find_one({"_id": ObjectId(message_id)})
#
#         if not message or message.get("file_type") != "photo" or not message.get("file_id"):
#             return {"error": "Photo not found"}
#
#         # Получаем file_path через Telegram API
#         file = await bot1.get_file(message["file_id"])
#         if not file.file_path:
#             return {"error": "File path missing"}
#
#         # Перенаправляем на Telegram CDN
#         photo_url = f"https://api.telegram.org/file/bot{bot1.token}/{file.file_path}"
#
#         from fastapi.responses import RedirectResponse
#         return RedirectResponse(photo_url)
#
#     except Exception as e:
#         logger.error(f"❌ Ошибка получения фото {message_id}: {e}")
#         return {"error": str(e)}

@router.get("/chats/photo/{message_id}")
async def get_chat_photo_stream(
    message_id: str,
    admin=Depends(get_current_admin)
):
    """Прокси фото с корректным именем и Content-Type"""
    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        db = get_database_bot1()
        messages_collection = db["messages"]

        from bson import ObjectId
        message = await messages_collection.find_one({"_id": ObjectId(message_id)})

        if not message or message.get("file_type") != "photo" or not message.get("file_id"):
            raise HTTPException(status_code=404, detail="Photo not found")

        file = await bot1.get_file(message["file_id"])
        if not file.file_path:
            raise HTTPException(status_code=404, detail="File path missing")

        photo_url = f"https://api.telegram.org/file/bot{bot1.token}/{file.file_path}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(photo_url)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch photo from Telegram")

            # Определяем тип и расширение
            content_type = resp.headers.get("content-type")
            if not content_type:
                # Telegram почти всегда отдаёт JPEG, fallback
                content_type = "image/jpeg"

            ext = mimetypes.guess_extension(content_type)
            if ext == ".jpe" or not ext:
                ext = ".jpg"

            # Имя: photo_{user_id}_{message_id}.jpg
            user_id = message.get("user_id", "unknown")
            filename = f"photo_{user_id}_{message_id}{ext}"

            headers = {
                "Content-Type": content_type,
                "Content-Disposition": f'attachment; filename="{quote(filename)}"',
                "Cache-Control": "private, max-age=86400",
            }

            async def stream_file():
                async for chunk in resp.aiter_bytes():
                    yield chunk

            return StreamingResponse(stream_file(), headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ get_chat_photo_stream({message_id}): {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# @router.get("/chats/photo-url/{message_id}")
# async def get_chat_photo_url(
#         message_id: str,
#         admin=Depends(get_current_admin)
# ):
#     """
#     Возвращает JSON с URL фото из Telegram CDN по message_id.
#     """
#     if not admin:
#         return {"error": "Unauthorized"}
#
#     try:
#         db = get_database_bot1()
#         messages_collection = db["messages"]
#
#         # 1. Находим сообщение по _id
#         from bson import ObjectId
#         message = await messages_collection.find_one({"_id": ObjectId(message_id)})
#
#         if not message or message.get("file_type") != "photo" or not message.get("file_id"):
#             return {"error": "Photo not found"}
#
#         # 2. Получаем file_path через Telegram API
#         file = await bot1.get_file(message["file_id"])
#         if not file.file_path:
#             return {"error": "File path missing from Telegram"}
#
#         # 3. Формируем публичный URL
#         photo_url = f"https://api.telegram.org/file/bot{bot1.token}/{file.file_path}"
#
#         return {"url": photo_url}
#
#     except Exception as e:
#         print(f"❌ Ошибка в /chats/photo-url/{message_id}: {e}")
#         return {"error": f"Failed to get photo URL: {str(e)}"}


@router.get("/chats/download/{message_id}")
async def download_file_stream(
    message_id: str,
    admin=Depends(get_current_admin)
):
    """Скачивание файла (документ, аудио, видео и др.) с корректным именем и Content-Type"""
    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        db = get_database_bot1()
        messages_collection = db["messages"]

        from bson import ObjectId
        message = await messages_collection.find_one({"_id": ObjectId(message_id)})

        if not message or not message.get("file_id"):
            raise HTTPException(status_code=404, detail="File not found")

        user_id = message.get("user_id", "unknown")
        file_type = message.get("file_type", "file")
        file_name_original = message.get("file_name")  # может быть None

        # Получаем file_path через Telegram API
        file = await bot1.get_file(message["file_id"])
        if not file.file_path:
            raise HTTPException(status_code=404, detail="File path missing")

        file_url = f"https://api.telegram.org/file/bot{bot1.token}/{file.file_path}"

        # Скачиваем потоком
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(file_url)
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch file from Telegram")

            # 1️⃣ Определяем content_type
            content_type = response.headers.get("content-type") or "application/octet-stream"

            # 2️⃣ Определяем расширение
            ext = mimetypes.guess_extension(content_type)
            if not ext:
                # fallback по file_path (часто есть .pdf, .ogg и т.д.)
                path_ext = file.file_path.split('.')[-1].lower() if '.' in file.file_path else ''
                if path_ext in {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'csv', 'json', 'xml', 'mp3', 'ogg', 'wav', 'mp4', 'mov', 'avi', 'mkv', 'jpg', 'jpeg', 'png', 'gif', 'webp'}:
                    ext = '.' + path_ext
                else:
                    ext = '.bin'

            if ext == '.jpe':
                ext = '.jpg'

            # 3️⃣ Генерируем имя файла
            # Базовое имя по типу
            type_name = {
                'document': 'document',
                'audio': 'audio',
                'voice': 'voice',
                'video': 'video',
                'video_note': 'video_note',
                'photo': 'photo',
                'animation': 'animation',
            }.get(file_type, 'file')

            # Если есть оригинальное имя — используем его (без пути и с нормализацией расширения)
            if file_name_original and file_name_original.strip():
                # Очищаем от опасных символов (оставляем буквы, цифры, точки, подчёркивания, дефисы, пробелы)
                safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in file_name_original.strip())
                # Сохраняем оригинальное расширение, если оно совпадает с реальным (или заменяем на корректное)
                if '.' in safe_name:
                    orig_ext = '.' + safe_name.rsplit('.', 1)[-1].lower()
                    if orig_ext == ext or (orig_ext in {'.jpeg', '.jpg'} and ext in {'.jpeg', '.jpg'}):
                        # Оставляем оригинальное расширение
                        filename = f"{type_name}_{user_id}_{message_id}_{safe_name}"
                    else:
                        # Меняем расширение на корректное
                        base = safe_name.rsplit('.', 1)[0]
                        filename = f"{type_name}_{user_id}_{message_id}_{base}{ext}"
                else:
                    filename = f"{type_name}_{user_id}_{message_id}_{safe_name}{ext}"
            else:
                filename = f"{type_name}_{user_id}_{message_id}{ext}"

            # 4️⃣ Заголовки
            headers = {
                "Content-Type": content_type,
                "Content-Disposition": f'attachment; filename="{quote(filename)}"',
                "Cache-Control": "private, max-age=86400",
            }

            # 5️⃣ Стриминг
            async def file_stream():
                async for chunk in response.aiter_bytes(8192):
                    yield chunk

            return StreamingResponse(file_stream(), headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания файла {message_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# @router.get("/chats/audio/{message_id}")
# async def stream_audio(
#         message_id: str,
#         admin=Depends(get_current_admin)
# ):
#     """Воспроизвести аудио"""
#     # Аналогично download_file, но для аудио
#     return await download_file(message_id, admin)
#
#
# @router.get("/chats/video/{message_id}")
# async def stream_video(
#         message_id: str,
#         admin=Depends(get_current_admin)
# ):
#     """Воспроизвести видео"""
#     # Аналогично download_file, но для видео
#     return await download_file(message_id, admin)


@router.post("/chats/send/")
async def send_operator_message(
        data: dict,
        admin=Depends(get_current_admin)
):
    """Отправить сообщение от оператора и пометить сообщения пользователя как прочитанные"""
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

        # 2. ОТМЕТКА: Помечаем ВСЕ сообщения пользователя как прочитанные
        await messages_collection.update_many(
            {
                "from_id": user_id,
                "from_operator": "0",  # только сообщения от пользователя
                "checked": "0"  # только непрочитанные
            },
            {
                "$set": {"checked": "1"}
            }
        )

        logger.info(f"✅ Помечены как прочитанные сообщения пользователя {user_id}")

        # 3. Отправляем сообщение пользователю в Telegram
        telegram_success = await send_telegram_message(user_id, text)

        # 4. Получаем следующий ID сообщения
        last_message = await messages_collection.find_one({}, sort=[("id", -1)])
        next_id = last_message["id"] + 1 if last_message else 1

        # 5. Сохраняем сообщение оператора в БД
        message_text = text
        if not telegram_success:
            message_text = text + " (не доставлено)"

        message_data = {
            "from_id": user_id,
            "message_object": message_text,
            "checked": "1",  # сообщение от оператора всегда прочитанное
            "date": datetime.now(timezone.utc),
            "file_id": "",
            "file_type": "text",
            "from_operator": "1",  # сообщение от оператора
            "id": next_id
        }

        await messages_collection.insert_one(message_data)

        return {
            "ok": True,
            "message_id": next_id,
            "delivered": telegram_success
        }

    except Exception as e:
        logger.error(f"❌ Ошибка отправки сообщения: {e}")
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
        logger.error(f"❌ Ошибка отправки в Telegram пользователю {user_id}: {e}")
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


@router.post("/chats/delete/")
async def delete_chat(
        request: Request,
        admin=Depends(get_current_admin)
):
    if not admin:
        return JSONResponse({"ok": False, "error": "Не авторизован"})

    try:
        data = await request.json()
        user_id = data.get("user_id")

        if not user_id:
            return JSONResponse({"ok": False, "error": "Не указан user_id"})

        # Получаем подключение к MongoDB
        db = get_database_bot1()
        messages_collection = db["messages"]

        # Удаляем все сообщения пользователя
        result = await messages_collection.delete_many({"from_id": user_id})

        # Также удаляем сообщения оператора этому пользователю (если есть)
        await messages_collection.delete_many({
            "$or": [
                {"from_id": user_id},
                {"to_id": user_id}
            ]
        })

        deleted_count = result.deleted_count

        return JSONResponse({
            "ok": True,
            "message": f"Чат с пользователем {user_id} удален. Удалено сообщений: {deleted_count}"
        })

    except Exception as e:
        logger.error(f"Ошибка удаления чата: {e}")
        return JSONResponse({"ok": False, "error": str(e)})