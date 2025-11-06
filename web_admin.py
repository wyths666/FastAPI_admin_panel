from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from api.router.bot2_claims import router as bot2_claims_router

from api.router import auth, main
from db.beanie.models import Administrators
from utils.database import init_database, check_connection

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Запуск FastAPI...")
    await init_database()
    success, message = await check_connection()
    print(message)
    yield
    # Shutdown
    print("🛑 Остановка FastAPI...")

app = FastAPI(
    title="Admin Panel",
    lifespan=lifespan
)


app.include_router(auth.router)
app.include_router(main.router)
app.include_router(bot2_claims_router)

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_admin:app", host="127.0.0.1", port=8000, reload=True)