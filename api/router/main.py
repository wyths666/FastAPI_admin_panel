from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from api.router.auth import get_current_admin
from db.beanie.models import Claim, ChatSession

router = APIRouter()
templates = Jinja2Templates(directory="api/templates")


# Главная страница
@router.get("/", response_class=HTMLResponse)
async def root(request: Request, admin=Depends(get_current_admin)):
    if not admin:
        return RedirectResponse("/auth/login")

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin": admin,
            "title": "Главная панель"
        }
    )


# Страницы ботов
@router.get("/bot1", response_class=HTMLResponse)
async def bot1_page(request: Request, admin=Depends(get_current_admin)):
    if not admin:
        return RedirectResponse("/auth/login")

    return templates.TemplateResponse(
        "bot1.html",
        {
            "request": request,
            "admin": admin,
            "title": "Бот 1"
        }
    )


@router.get("/")
async def bot2_root(admin=Depends(get_current_admin)):
    """Перенаправление на страницу заявок"""
    return RedirectResponse("/bot2/claims/")


@router.get("/dashboard", response_class=HTMLResponse)
async def bot2_dashboard(request: Request, admin=Depends(get_current_admin)):
    # Статистика по заявкам - ПРАВИЛЬНЫЙ СИНТАКСИС
    total_claims = await Claim.count()
    pending_claims = await Claim.find({"claim_status": "pending"}).count()

    # Заявки с неотвеченными сообщениями
    unanswered_sessions = await ChatSession.find({"has_unanswered": True, "is_active": True}).count()

    return templates.TemplateResponse(
        "bot2_dashboard.html",
        {
            "request": request,
            "admin": admin,
            "title": "Бот 2 - Панель управления",
            "stats": {
                "total_claims": total_claims,
                "pending_claims": pending_claims,
                "unanswered_chats": unanswered_sessions
            }
        }
    )