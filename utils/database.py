from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from config import cnf
from db.beanie.models import Administrators
from db.beanie.models import document_models
from db.beanie_bot1.models import document_models as bot1_models
_client = None
_is_initialized = False


async def init_database():
    """Инициализация БД - может вызываться многократно безопасно"""
    global _client, _is_initialized

    if _is_initialized:
        return _client[cnf.mongo.NAME]

    _client = AsyncIOMotorClient(cnf.mongo.URL)
    database = _client[cnf.mongo.NAME]

    await init_beanie(
        database=database,
        document_models=document_models
    )

    _is_initialized = True
    print("✅ База данных инициализирована")
    return database


async def init_database_bot1():
    """Инициализация БД - может вызываться многократно безопасно"""
    global _client, _is_initialized

    if _is_initialized:
        return _client[cnf.mongo_bot1.NAME]

    _client = AsyncIOMotorClient(cnf.mongo_bot1.URL)
    database = _client[cnf.mongo_bot1.NAME]

    await init_beanie(
        database=database,
        document_models=bot1_models
    )

    _is_initialized = True
    print("✅ База данных Бот-1 инициализирована")
    return database


def get_database():
    """Получить базу данных (только после инициализации)"""
    if not _is_initialized:
        raise RuntimeError("База данных не инициализирована. Сначала вызовите init_database()")
    return _client[cnf.mongo.NAME]

def get_database_bot1():
    """Получить базу данных (только после инициализации)"""
    if not _is_initialized:
        raise RuntimeError("База данных не инициализирована. Сначала вызовите init_database()")
    return _client[cnf.mongo_bot1.NAME]


async def check_connection():
    """Проверить подключение к БД"""
    try:
        count = await Administrators.count()
        return True, f"✅ Подключение к БД успешно, администраторов: {count}"
    except Exception as e:
        return False, f"❌ Ошибка подключения к БД: {e}"