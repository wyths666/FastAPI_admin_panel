from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from config import cnf
from db.beanie.models import Administrators
from db.beanie.models import document_models
from db.beanie_bot1.models import document_models as bot1_models

# Раздельные клиенты для разных баз
_client_main = None
_client_bot1 = None
_is_initialized_main = False
_is_initialized_bot1 = False


async def init_database():
    """Инициализация основной БД"""
    global _client_main, _is_initialized_main

    if _is_initialized_main:
        return _client_main[cnf.mongo.NAME]

    _client_main = AsyncIOMotorClient(cnf.mongo.URL)
    database = _client_main[cnf.mongo.NAME]

    await init_beanie(
        database=database,
        document_models=document_models
    )

    _is_initialized_main = True
    print("✅ Основная база данных инициализирована")
    return database


async def init_database_bot1():
    """Инициализация БД для бота-1"""
    global _client_bot1, _is_initialized_bot1

    if _is_initialized_bot1:
        return _client_bot1[cnf.mongo_bot1.NAME]

    _client_bot1 = AsyncIOMotorClient(cnf.mongo_bot1.URL)
    database = _client_bot1[cnf.mongo_bot1.NAME]

    await init_beanie(
        database=database,
        document_models=bot1_models
    )

    _is_initialized_bot1 = True
    print("✅ База данных Бот-1 инициализирована")

    # Проверяем загрузку данных
    from db.beanie_bot1.models import Users, Products, Messages
    users_count = await Users.count()
    products_count = await Products.count()
    messages_count = await Messages.count()

    print(f"📊 Загружено из Бот-1: {users_count} пользователей, {products_count} товаров, {messages_count} сообщений")

    return database


def get_database():
    """Получить основную базу данных"""
    if not _client_main:
        raise RuntimeError("Основная база данных не инициализирована")
    return _client_main[cnf.mongo.NAME]


def get_database_bot1():
    """Получить базу данных бота-1"""
    if not _client_bot1:
        raise RuntimeError("База данных бота-1 не инициализирована")
    return _client_bot1[cnf.mongo_bot1.NAME]


async def check_connection():
    """Проверить подключение к основной БД"""
    try:
        count = await Administrators.count()
        return True, f"✅ Подключение к БД бота-2 успешно, администраторов: {count}"
    except Exception as e:
        return False, f"❌ Ошибка подключения к основной БД: {e}"


async def check_connection_bot1():
    """Проверить подключение к БД бота-1"""
    try:
        from db.beanie_bot1.models import Users
        count = await Users.count()
        return True, f"✅ Подключение к БД бота-1 успешно, пользователей: {count}"
    except Exception as e:
        return False, f"❌ Ошибка подключения к БД бота-1: {e}"


def get_messages_collection_bot1():
    """Получить коллекцию messages бота-1"""
    return get_database_bot1()["messages"]

def get_users_collection_bot1():
    """Получить коллекцию users бота-1"""
    return get_database_bot1()["users"]