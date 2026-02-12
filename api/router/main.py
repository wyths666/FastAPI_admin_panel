from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from api.router.auth import get_current_admin

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


@router.get("/")
async def bot2_root(admin=Depends(get_current_admin)):
    """Перенаправление на страницу заявок"""
    return RedirectResponse("/bot2/claims/")


