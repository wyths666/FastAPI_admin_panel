from aiogram import Router, F
from aiogram.types import Message, ContentType
from aiogram.filters import Command
from db.beanie_bot1.models.models import Messages
from datetime import datetime, timezone
from utils.database import get_database_bot1

# Создаем роутер
user_messages_router = Router()

# Исключаем команды
user_messages_router.message.filter(~F.text.startswith('/'))


@user_messages_router.message(F.content_type.in_({
    ContentType.TEXT,
    ContentType.PHOTO,
    ContentType.DOCUMENT,
    ContentType.VIDEO,
    ContentType.AUDIO,
    ContentType.VOICE,
    ContentType.STICKER,
    ContentType.VIDEO_NOTE
}))
async def handle_user_message(message: Message):
    """Обрабатывает все сообщения пользователей кроме команд"""

    # Пропускаем служебные сообщения
    if not message.from_user:
        return

    user_id = message.from_user.id
    username = message.from_user.username
    full_name = get_full_name(message.from_user)

    try:
        # Получаем следующий ID сообщения
        next_id = await get_next_message_id()

        # Определяем тип контента и извлекаем данные
        message_data = await extract_message_data(message)

        # Сохраняем сообщение в MongoDB
        await save_user_message(
            user_id=user_id,
            username=username,
            full_name=full_name,
            message_data=message_data,
            message_id=next_id
        )

        # Логируем для отладки
        print(
            f"💾 Сохранено сообщение от {user_id}: {message_data['file_type']} - {message_data['message_object'][:50]}...")

    except Exception as e:
        print(f"❌ Ошибка сохранения сообщения: {e}")


async def extract_message_data(message: Message) -> dict:
    """Извлекает данные из сообщения в зависимости от типа контента"""

    message_object = ""
    file_id = ""
    file_type = "none"
    file_name = ""
    file_size = 0
    mime_type = ""

    if message.text:
        # Текстовое сообщение
        message_object = message.text
        file_type = "text"

    elif message.photo:
        # Фото
        message_object = message.caption or ""
        file_id = message.photo[-1].file_id  # Берем самое качественное фото
        file_type = "photo"
        file_size = message.photo[-1].file_size or 0

    elif message.document:
        # Документ (файл)
        message_object = message.caption or ""
        file_id = message.document.file_id
        file_type = "document"
        file_name = message.document.file_name or "Без названия"
        file_size = message.document.file_size or 0
        mime_type = message.document.mime_type or ""

        # Формируем информативное описание файла
        if not message_object:
            file_info = []
            if file_name:
                file_info.append(f"📎 {file_name}")
            if file_size:
                size_mb = file_size / 1024 / 1024
                file_info.append(f"({size_mb:.1f} MB)")
            if mime_type:
                file_info.append(f"[{mime_type}]")

            message_object = " ".join(file_info) if file_info else "📎 Файл"

    elif message.video:
        # Видео
        message_object = message.caption or "🎥 Видео"
        file_id = message.video.file_id
        file_type = "video"
        file_size = message.video.file_size or 0
        mime_type = message.video.mime_type or ""

    elif message.audio:
        # Аудио
        message_object = message.caption or "🎵 Аудио"
        file_id = message.audio.file_id
        file_type = "audio"
        file_size = message.audio.file_size or 0
        mime_type = message.audio.mime_type or ""

        # Добавляем информацию о треке
        audio_info = []
        if message.audio.title:
            audio_info.append(message.audio.title)
        if message.audio.performer:
            audio_info.append(f"- {message.audio.performer}")
        if audio_info and not message.caption:
            message_object = "🎵 " + " ".join(audio_info)

    elif message.voice:
        # Голосовое сообщение
        message_object = "🎤 Голосовое сообщение"
        file_id = message.voice.file_id
        file_type = "voice"
        file_size = message.voice.file_size or 0

    elif message.sticker:
        # Стикер
        message_object = "🔄 Стикер"
        file_id = message.sticker.file_id
        file_type = "sticker"

        # Добавляем эмодзи стикера если есть
        if message.sticker.emoji:
            message_object = f"{message.sticker.emoji} Стикер"

    elif message.video_note:
        # Кружочек (video note)
        message_object = "📹 Видео-кружочек"
        file_id = message.video_note.file_id
        file_type = "video_note"
        file_size = message.video_note.file_size or 0

    return {
        "message_object": message_object,
        "file_id": file_id,
        "file_type": file_type,
        "file_name": file_name,
        "file_size": file_size,
        "mime_type": mime_type
    }

def get_full_name(user):
    """Получить полное имя пользователя"""
    full_name = []
    if user.first_name:
        full_name.append(user.first_name)
    if user.last_name:
        full_name.append(user.last_name)
    return " ".join(full_name) if full_name else ""


async def get_next_message_id() -> int:
    """Получить следующий ID для сообщения"""
    db = get_database_bot1()
    messages_collection = db["messages"]

    # Находим последнее сообщение по полю id
    last_message = await messages_collection.find_one(
        {},
        sort=[("id", -1)]
    )

    return last_message["id"] + 1 if last_message else 1

async def save_user_message(user_id: int, username: str, full_name: str,
                            message_data: dict, message_id: int):
    """Сохраняет сообщение пользователя в MongoDB"""

    db = get_database_bot1()
    messages_collection = db["messages"]
    users_collection = db["users"]

    # Сохраняем сообщение
    message_doc = {
        "from_id": user_id,
        "message_object": message_data["message_object"],
        "checked": "0",  # Не прочитано оператором
        "date": datetime.now(timezone.utc),
        "file_id": message_data["file_id"],
        "file_type": message_data["file_type"],
        "from_operator": "0",  # Сообщение от пользователя
        "id": message_id,
        "file_name": message_data["file_name"],
        "file_size": message_data["file_size"],
        "mime_type": message_data["mime_type"]
    }

    await messages_collection.insert_one(message_doc)

    # Обновляем/создаем запись пользователя
    await users_collection.update_one(
        {"id": user_id},
        {
            "$set": {
                "username": username,
                "full_name": full_name,
                "role": "user",
                "banned": "0"
            },
            "$setOnInsert": {
                "id": user_id
            }
        },
        upsert=True
    )