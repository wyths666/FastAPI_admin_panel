# api/routers/auth.py
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
import secrets
from core.logger import api_logger as logger
from db.beanie.models import Administrators

router = APIRouter(prefix="/auth", tags=["authentication"])
templates = Jinja2Templates(directory="api/templates")


# Зависимость для проверки авторизации
async def get_current_admin(request: Request):
    token = request.cookies.get("admin_token")
    if token:
        admin = await Administrators.get(session_token=token, is_active=True)
        return admin
    return None


# Страница логина
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, admin=Depends(get_current_admin)):
    if admin:
        return RedirectResponse("/")

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "title": "Авторизация"
        }
    )


# Обработка логина
@router.post("/login", response_class=HTMLResponse)
async def login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...)
):
    try:
        logger.warning(f"🔐 Попытка входа: логин='{username}', пароль='{password}'")

        # Ищем администратора
        admin = await Administrators.get(login=username, is_active=True)

        if not admin:
            logger.error(f"❌ Администратор с логином '{username}' не найден")
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "Неверный логин или пароль",
                    "username": username,
                    "title": "Авторизация"
                }
            )

        logger.info(f"✅ Найден администратор: {admin.login}")

        # Проверяем пароль
        if admin.password != password:
            logger.error("❌ Неверный пароль")
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "Неверный логин или пароль",
                    "username": username,
                    "title": "Авторизация"
                }
            )

        logger.info("✅ Пароль верный!")

        # Генерируем токен сессии
        session_token = secrets.token_urlsafe(32)
        await admin.update(
            session_token=session_token,
            last_login=datetime.utcnow()
        )

        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            key="admin_token",
            value=session_token,
            httponly=True,
            max_age=24 * 60 * 60
        )

        logger.info(f"✅ Успешный вход для {admin.login}")
        return response

    except Exception as e:
        logger.error(f"💥 Ошибка при логине: {e}")
        import traceback
        traceback.print_exc()

        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Ошибка сервера. Попробуйте позже.",
                "title": "Авторизация"
            }
        )


# Логаут
@router.get("/logout")
async def logout(request: Request):
    # Находим администратора по токену и очищаем его
    token = request.cookies.get("admin_token")
    if token:
        admin = await Administrators.get(session_token=token)
        if admin:
            await admin.update(session_token=None)

    # Редирект на страницу логина
    response = RedirectResponse("/auth/login", status_code=302)
    response.delete_cookie("admin_token")
    return response


# API эндпоинты для отладки
@router.get("/debug-admins")
async def debug_admins():
    """Посмотреть всех администраторов из базы"""
    admins = await Administrators.all()

    result = []
    for admin in admins:
        result.append({
            "id": str(admin.id),
            "admin_id": admin.admin_id,
            "login": admin.login,
            "password": admin.password,
            "is_active": admin.is_active,
            "created_at": admin.created_at.isoformat() if admin.created_at else None
        })

    return result


@router.get("/check-auth")
async def check_auth(admin=Depends(get_current_admin)):
    """Проверить текущую авторизацию"""
    return {
        "authenticated": admin is not None,
        "admin": admin.login if admin else None
    }