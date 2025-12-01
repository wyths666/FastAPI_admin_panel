from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from api.router.claims import router as claims_router
from api.router.chats import router as chats_router
from api.router.payments import router as payments_router
from api.router import auth, main, supports_router
from db.beanie.models import Administrators
from utils.database import init_database, check_connection, init_database_bot1, check_connection_bot1


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Запуск FastAPI...")

    # Инициализируем обе базы данных
    await init_database_bot1()
    await init_database()

    # Проверяем оба подключения
    success_main, message_main = await check_connection()
    success_bot1, message_bot1 = await check_connection_bot1()

    print(message_main)
    print(message_bot1)

    if not success_main or not success_bot1:
        print("❌ Критическая ошибка: не удалось подключиться к базам данных")

    yield

    # Shutdown
    print("🛑 Остановка FastAPI...")


app = FastAPI(
    title="Admin Panel",
    lifespan=lifespan
)

app.include_router(auth.router)
app.include_router(main.router)
app.include_router(claims_router)
app.include_router(chats_router)
app.include_router(payments_router)
app.include_router(supports_router)

# Эндпоинты для проверки
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "admin_panel"}


@app.get("/check-db")
async def check_db():
    try:
        count = await Administrators.count()
        return {"status": "ok", "admin_count": count}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/check-db-bot1")
async def check_db_bot1():
    try:
        from db.beanie_bot1.models import Users
        count = await Users.count()
        return {"status": "ok", "users_count": count}
    except Exception as e:
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web_admin:app", host="0.0.0.0", port=8000, reload=True)