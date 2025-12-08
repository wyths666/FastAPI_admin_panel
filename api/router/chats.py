from fastapi.responses import StreamingResponse
import httpx
from fastapi import UploadFile, File, Form
import time
from typing import Dict, Any, Tuple
import hashlib
import json
from aiogram.types import BufferedInputFile
import time
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


# In-memory кэш
chat_cache = {}
CACHE_TTL = 15


def get_cache_key(username, user_id, date_from, date_to, has_unread, page):
    """Создает уникальный ключ кэша на основе параметров"""
    params_str = f"{username}_{user_id}_{date_from}_{date_to}_{has_unread}_{page}"
    return hashlib.md5(params_str.encode()).hexdigest()





@router.get("/chats/", response_class=HTMLResponse)
async def chats_page(
        request: Request,
        username: Optional[str] = Query(None),
        user_id: Union[str, None] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        has_unread: Optional[bool] = Query(None),
        page: int = Query(1, ge=1),
        admin=Depends(get_current_admin)
):
    if not admin:
        return RedirectResponse("/auth/login")

    # Создаем ключ кэша
    cache_key = get_cache_key(username, user_id, date_from, date_to, has_unread, page)

    # Проверяем кэш
    current_time = time.time()
    if cache_key in chat_cache:
        cached_data, timestamp = chat_cache[cache_key]
        if current_time - timestamp < CACHE_TTL:
            logger.info(f"✅ Используем кэш для страницы {page}")
            return templates.TemplateResponse("chats.html", {
                "request": request,
                "chats": cached_data["chats"],
                "username": username,
                "user_id": cached_data["user_id"],
                "date_from": date_from,
                "date_to": date_to,
                "has_unread": has_unread,
                "current_page": page,
                "total_pages": cached_data["total_pages"],
                "total_chats": cached_data["total_chats"],
                "start_chat": cached_data["start_chat"],
                "end_chat": cached_data["end_chat"]
            })

    # Если кэша нет или устарел, загружаем данные
    db = get_database_bot1()
    messages_collection = db["messages"]

    page_size = 50
    skip = (page - 1) * page_size

    # === 1. Фильтр по user_id (строка -> int) ===
    filter_user_id: Optional[int] = None
    if user_id is not None and user_id.strip() != "":
        try:
            filter_user_id = int(user_id.strip())
        except (ValueError, TypeError):
            pass  # игнорируем некорректный ID

    # === 2. Формируем базовый $match для messages ===
    match_filters = {}

    if filter_user_id is not None:
        match_filters["from_id"] = filter_user_id

    # Дата
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
            match_filters["date"] = date_filter

    # === 3. Построение агрегационного pipeline с $lookup ===
    pipeline = []

    # Базовый фильтр по messages (user_id, дата)
    if match_filters:
        pipeline.append({"$match": match_filters})

    # Джойним users
    pipeline.append({
        "$lookup": {
            "from": "users",
            "localField": "from_id",
            "foreignField": "id",
            "as": "user_doc"
        }
    })
    pipeline.append({"$unwind": {"path": "$user_doc", "preserveNullAndEmptyArrays": True}})

    # Ранний фильтр по username — до группировки!
    if username and username.strip():
        pipeline.append({
            "$match": {
                "user_doc.username": {"$regex": username.strip(), "$options": "i"}
            }
        })

    # Группируем по пользователю
    pipeline.extend([
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
            },
            # Сохраняем данные пользователя — экономим 1 запрос
            "username": {"$first": {"$ifNull": ["$user_doc.username", {"$concat": ["id", {"$toString": "$from_id"}]}]}},
            "full_name": {"$first": {"$ifNull": ["$user_doc.full_name", "Неизвестный пользователь"]}},
            "banned": {"$first": {"$ifNull": ["$user_doc.banned", "0"]}},
        }},
        {"$sort": {"last_message_date": -1}}
    ])

    # Фильтр по непрочитанным — после группировки
    if has_unread is True:
        pipeline.append({"$match": {"unread_count": {"$gt": 0}}})

    # Подсчёт total
    count_pipeline = pipeline + [{"$count": "total"}]
    total_chats_result = await messages_collection.aggregate(count_pipeline).to_list(length=None)
    total_chats = total_chats_result[0]["total"] if total_chats_result else 0
    total_pages = (total_chats + page_size - 1) // page_size

    # Коррекция текущей страницы
    page = max(1, min(page, total_pages or 1))
    skip = (page - 1) * page_size

    # Пагинация
    pipeline.extend([
        {"$skip": skip},
        {"$limit": page_size}
    ])

    # Выполнение
    chats_aggregation = await messages_collection.aggregate(pipeline).to_list(length=None)

    # === 4. Формирование данных ===
    chats_data = []
    for chat in chats_aggregation:
        # Последнее сообщение для превью
        last_message = await messages_collection.find_one(
            {"from_id": chat["_id"]},
            sort=[("date", -1)]
        )

        last_message_text = ""
        has_photo = False
        if last_message:
            msg_obj = last_message.get("message_object", "")
            last_message_text = (msg_obj[:100] + "..." if len(msg_obj) > 100 else msg_obj) or "(без текста)"
            has_photo = last_message.get("file_type") == "photo"

        chats_data.append({
            "user_id": chat["_id"],
            "username": chat["username"],
            "full_name": chat["full_name"],
            "banned": chat["banned"],
            "last_message_date": chat["last_message_date"],
            "message_count": chat["message_count"],
            "unread_count": chat["unread_count"],
            "last_message_preview": last_message_text,
            "has_photo": has_photo
        })

    # Диапазон отображения
    start_chat = skip + 1 if total_chats > 0 else 0
    end_chat = min(skip + len(chats_data), total_chats)

    # Сохраняем в кэш
    cache_data = {
        "chats": chats_data,
        "user_id": filter_user_id,
        "total_pages": total_pages,
        "total_chats": total_chats,
        "start_chat": start_chat,
        "end_chat": end_chat
    }
    chat_cache[cache_key] = (cache_data, current_time)

    logger.info(f"✅ Данные закэшированы для страницы {page}")

    return templates.TemplateResponse("chats.html", {
        "request": request,
        "chats": chats_data,
        "username": username,
        "user_id": filter_user_id,
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
            "checked": msg.get("checked", "0") == "1",
            "has_photo": msg.get("file_type") == "photo" and bool(msg.get("file_id")),
            "file_name": msg.get("file_name", ""),
            "file_size": msg.get("file_size", 0),
            "mime_type": msg.get("mime_type", ""),
            "has_document": msg.get("file_type") == "document" and bool(msg.get("file_id")),
            "has_audio": msg.get("file_type") in ["audio", "voice"] and bool(msg.get("file_id")),
            "has_video": msg.get("file_type") in ["video", "video_note"] and bool(msg.get("file_id"))
        })

    return messages_data


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

        filename = f"photo_{message_id}.jpg"

        file = await bot1.get_file(message["file_id"])
        if not file.file_path:
            raise HTTPException(status_code=404, detail="File path missing")

        file_url = f"https://api.telegram.org/file/bot{bot1.token}/{file.file_path}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(file_url)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch photo")

            headers = {
                "Content-Type": "image/jpeg",
                "Content-Disposition": f'attachment; filename="{quote(filename)}"',
                "Cache-Control": "private, max-age=86400",
            }

            async def file_stream():
                async for chunk in resp.aiter_bytes(65536):
                    yield chunk

            return StreamingResponse(file_stream(), headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ get_chat_photo_stream({message_id}): {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/chats/download/{message_id}")
async def download_file_stream(
        message_id: str,
        admin=Depends(get_current_admin)
):
    """Скачивание файла с корректным именем и Content-Type"""
    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        db = get_database_bot1()
        messages_collection = db["messages"]

        from bson import ObjectId
        message = await messages_collection.find_one({"_id": ObjectId(message_id)})

        if not message or not message.get("file_id"):
            raise HTTPException(status_code=404, detail="File not found")

        file_name_original = message.get("file_name", "")
        db_mime_type = message.get("mime_type", "")


        file = await bot1.get_file(message["file_id"])
        if not file.file_path:
            raise HTTPException(status_code=404, detail="File path missing")

        file_url = f"https://api.telegram.org/file/bot{bot1.token}/{file.file_path}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            head_resp = await client.head(file_url)
            if head_resp.status_code != 200:
                raise HTTPException(status_code=502, detail="File unavailable on Telegram CDN")

            db_mime_type = (message.get("mime_type") or "").strip()
            head_mime_type = (head_resp.headers.get("content-type") or "").strip()
            content_type = db_mime_type or head_mime_type or "application/octet-stream"

            if file_name_original and file_name_original.strip():
                safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in file_name_original.strip())
                filename = safe_name
            else:
                if file.file_path and '.' in file.file_path:
                    ext = '.' + file.file_path.rsplit('.', 1)[-1].lower()
                else:
                    ext = '.bin'
                filename = f"{message_id}{ext}"

            print(f"📁 Финальное имя файла: {filename}")

            headers = {
                "Content-Type": content_type,
                "Content-Disposition": f'attachment; filename="{quote(filename)}"',
                "Cache-Control": "private, max-age=86400",
            }

            full_resp = await client.get(file_url)
            if full_resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch file body")

            async def file_stream():
                async for chunk in full_resp.aiter_bytes(65536):
                    yield chunk

            return StreamingResponse(file_stream(), headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания файла {message_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/chats/download-simple/{message_id}")
async def download_file_simple(
        message_id: str,
        admin=Depends(get_current_admin)
):
    """Упрощенное скачивание файла"""
    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db = get_database_bot1()
    messages_collection = db["messages"]

    from bson import ObjectId
    message = await messages_collection.find_one({"_id": ObjectId(message_id)})

    if not message or not message.get("file_id"):
        raise HTTPException(status_code=404, detail="File not found")

    # ПРОСТО ИСПОЛЬЗУЕМ ОРИГИНАЛЬНОЕ ИМЯ
    filename = message.get("file_name", f"file_{message_id}").strip()

    # Получаем file_path
    file = await bot1.get_file(message["file_id"])
    if not file.file_path:
        raise HTTPException(status_code=404, detail="File path missing")

    file_url = f"https://api.telegram.org/file/bot{bot1.token}/{file.file_path}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(file_url)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch file")

        headers = {
            "Content-Type": resp.headers.get("content-type", "application/octet-stream"),
            "Content-Disposition": f'attachment; filename="{quote(filename)}"',
        }

        async def file_stream():
            async for chunk in resp.aiter_bytes(65536):
                yield chunk

        return StreamingResponse(file_stream(), headers=headers)

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

    if len(text) > 4000:
        return {"error": "Сообщение слишком длинное (макс. 4000 символов)"}

    db = get_database_bot1()
    messages_collection = db["messages"]

    try:
        users_collection = db["users"]
        user = await users_collection.find_one({"id": user_id})

        if user and user.get("banned") == "1":
            return {"error": "Пользователь заблокирован"}

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

        logger.info(f"✅ Помечены как прочитанные сообщения пользователя {user_id}")

        telegram_success = await send_telegram_message(user_id, text)

        last_message = await messages_collection.find_one({}, sort=[("id", -1)])
        next_id = last_message["id"] + 1 if last_message else 1

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
        logger.error(f"❌ Ошибка отправки сообщения: {e}")
        return {"error": f"Внутренняя ошибка: {str(e)}"}


@router.post("/chats/send/file/")
async def send_operator_file(
    user_id: int = Form(...),
    file: UploadFile = File(...),
    caption: str = Form(""),
    admin=Depends(get_current_admin)
):
    """Отправка файла от оператора пользователю — без Pydantic, как в /chats/send/"""
    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        # 1. Проверка блокировки
        db = get_database_bot1()
        users_collection = db["users"]
        user = await users_collection.find_one({"id": user_id})
        if user and user.get("banned") == "1":
            raise HTTPException(status_code=403, detail="Пользователь заблокирован")

        # 2. Чтение файла
        contents = await file.read()
        file_size = len(contents)
        if file_size > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 50MB)")

        filename = file.filename or f"file_{int(time.time())}"
        mime_type = file.content_type or "application/octet-stream"
        input_file = BufferedInputFile(contents, filename=filename)

        # 3. Отправка в Telegram
        file_type = "document"
        file_id = ""
        msg = None

        try:
            if mime_type.startswith("image/"):
                msg = await bot1.send_photo(chat_id=user_id, photo=input_file, caption=caption[:1024] or None)
                file_type = "photo"
                file_id = msg.photo[-1].file_id if msg.photo else ""
            elif mime_type.startswith("video/"):
                msg = await bot1.send_video(chat_id=user_id, video=input_file, caption=caption[:1024] or None)
                file_type = "video"
                file_id = msg.video.file_id if msg.video else ""
            elif mime_type.startswith("audio/"):
                msg = await bot1.send_audio(chat_id=user_id, audio=input_file, caption=caption[:1024] or None)
                file_type = "audio"
                file_id = msg.audio.file_id if msg.audio else ""
            else:
                msg = await bot1.send_document(chat_id=user_id, document=input_file, caption=caption[:1024] or None)
                file_type = "document"
                file_id = msg.document.file_id if msg.document else ""
        except Exception as e:
            logger.error(f"❌ Telegram отправка не удалась: {e}")
            # Не прерываем — сохраним как "не доставлено", как в send/
            pass

        # 4. Генерация next_id — КАК В send/ !
        messages_collection = db["messages"]
        last_message = await messages_collection.find_one(
            {},
            sort=[("id", -1)],
            projection={"id": 1}
        )
        next_id = last_message["id"] + 1 if last_message else 1

        # 5. Подготовка данных — как в send/
        if file_type == "photo":
            message_text = caption or ""
        else:
            message_text = caption or f"📎 {filename}"
        if msg is None:  # Telegram не отправился
            message_text += " (не доставлено)"

        message_data = {
            "from_id": user_id,
            "message_object": message_text,
            "checked": "1",
            "date": datetime.now(timezone.utc),
            "file_id": file_id,
            "file_type": file_type,
            "from_operator": "1",
            "id": next_id,
            "file_name": filename,
            "file_size": file_size,
            "mime_type": mime_type
        }

        await messages_collection.insert_one(message_data)

        return {
            "ok": True,
            "message_id": next_id,
            "file_type": file_type,
            "filename": filename,
            "delivered": msg is not None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка отправки файла: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Не удалось отправить файл: {str(e)}")



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

        db = get_database_bot1()
        messages_collection = db["messages"]

        result = await messages_collection.delete_many({"from_id": user_id})

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