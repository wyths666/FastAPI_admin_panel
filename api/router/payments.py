from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
import math
import uuid
import json
from pathlib import Path
from beanie import PydanticObjectId

from api.schemas.konsol import PaymentResponse, HandPaymentResponse, PaymentCreateRequest
from core.logger import api_logger as logger
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response, RedirectResponse
from api.router.auth import get_current_admin
from api.schemas.response import ClaimResponse, ChatMessageSchema

from config import cnf
from core.bot import bot
from db.beanie.models import Claim, UserMessage, ChatSession, User, AdminMessage
from db.beanie.models.models import ChatMessage, KonsolPayment
from utils.database import get_database_bot1
from utils.konsol_client import konsol_client


templates = Jinja2Templates(directory="api/templates")
router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/create", response_class=HTMLResponse)
async def payment_form_page(request: Request):
    """Страница с формой создания выплаты"""

    # Загружаем банки из JSON файла
    banks_data = {}
    banks_file = Path("utils/banks.json")

    if banks_file.exists():
        try:
            with open(banks_file, 'r', encoding='utf-8') as f:
                banks_data = json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки banks.json: {e}")
            banks_data = {}
    else:
        print("Файл banks.json не найден")
        # Запасной вариант
        banks_data = {
            "100000000004": "Тинькофф",
            "100000000111": "Сбербанк",
            "100000000005": "ВТБ",
            "100000000008": "Альфа-Банк",
            "100000000015": "Газпромбанк",
            "100000000002": "Райффайзенбанк",
        }

    return templates.TemplateResponse("payments.html", {
        "request": request,
        "banks": banks_data
    })


@router.post("/create-payment", response_model=PaymentResponse)
async def create_payment(payment_data: PaymentCreateRequest):
    """Создание ручной выплаты через Konsol API"""
    try:
        print(f"🔍 Получены данные для ручной выплаты: {payment_data}")

        # === 1. Создаём НОВОГО contract_id в Konsol API ===
        # Генерируем уникальный номер выплаты
        from datetime import datetime
        payment_number = str(int(datetime.utcnow().timestamp()))[-6:].zfill(6)

        # Форматируем телефон
        phone = payment_data.phone
        if phone and payment_data.payment_type == "fps":
            # Приводим телефон к формату +7XXXXXXXXXX
            phone = phone.replace(" ", "").replace("-", "").replace("+", "")
            if phone.startswith("7") and len(phone) == 11:
                phone = "+" + phone
            elif phone.startswith("8") and len(phone) == 11:
                phone = "+7" + phone[1:]
            elif len(phone) == 10:
                phone = "+7" + phone
            else:
                raise HTTPException(status_code=400, detail="Неверный формат телефона. Пример: +7 900 123-45-67")

        contractor_phone = phone if payment_data.payment_type == "fps" else f"+79000{payment_number}"

        contractor_data = {
            "kind": "individual",
            "first_name": payment_data.first_name,
            "last_name": payment_data.last_name,
            "phone": contractor_phone
        }

        print(f"👤 Создаем contractor: {contractor_data}")

        try:
            contractor_result = await konsol_client.create_contractor(contractor_data)
            contractor_id = contractor_result["id"]
            print(f"✅ Contractor создан: {contractor_id}")

        except Exception as e:
            print(f"❌ Ошибка создания contractor: {e}")
            raise HTTPException(status_code=400, detail=f"Ошибка создания получателя: {str(e)}")

        # === 2. Подготавливаем данные для платежа ===
        bank_details_kind = "fps" if payment_data.payment_type == "fps" else "card"

        if bank_details_kind == "fps":
            if not payment_data.bank_member_id:
                raise HTTPException(status_code=400, detail="Не указан ID банка для СБП")
            if not phone:
                raise HTTPException(status_code=400, detail="Не указан номер телефона для СБП")

            bank_details = {
                "fps_mobile_phone": phone,
                "fps_bank_member_id": payment_data.bank_member_id
            }
        else:
            # Убираем пробелы из номера карты
            card_number = payment_data.card_number.replace(" ", "") if payment_data.card_number else None
            if not card_number:
                raise HTTPException(status_code=400, detail="Не указан номер карты")
            bank_details = {
                "card_number": card_number
            }

        payment_request_data = {
            "contractor_id": contractor_id,
            "services_list": [
                {
                    "title": f"Ручная выплата #{payment_number}",
                    "amount": str(payment_data.amount)
                }
            ],
            "bank_details_kind": bank_details_kind,
            "bank_details": bank_details,
            "purpose": payment_data.purpose,
            "amount": str(payment_data.amount)
        }

        print(f"💰 Данные платежа: {payment_request_data}")

        # === 3. Создаём платёж в Konsol API ===
        try:
            result = await konsol_client.create_payment(payment_request_data)
            payment_id = result.get("id")
            payment_status = result.get("status")
            services_list = result.get("services_list", [])
            bank_details_response = result.get("bank_details", {})
            created_at = result.get("created_at")
            updated_at = result.get("updated_at")
            paid_at = result.get("paid_at")

            print(f"✅ Платеж создан: {payment_id}, статус: {payment_status}")

            # === 4. Сохраняем платёж в БД ===
            db = get_database_bot1()
            payments_collection = db["konsol_payments"]

            payment_doc = {
                "konsol_id": payment_id,
                "contractor_id": contractor_id,
                "amount": float(payment_data.amount),
                "status": payment_status,
                "purpose": payment_data.purpose,
                "services_list": services_list,
                "bank_details_kind": bank_details_kind,
                "card_number": payment_data.card_number.replace(" ", "") if payment_data.card_number else None,
                "phone_number": phone,
                "bank_member_id": payment_data.bank_member_id,
                "first_name": payment_data.first_name,
                "last_name": payment_data.last_name,
                "payment_number": payment_number,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }

            await payments_collection.insert_one(payment_doc)
            print(f"✅ Платеж сохранен в БД")

            # Преобразуем даты из строк в datetime если нужно
            if created_at and isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if updated_at and isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            if paid_at and isinstance(paid_at, str):
                paid_at = datetime.fromisoformat(paid_at.replace('Z', '+00:00'))

            return PaymentResponse(
                id=payment_id,
                contractor_id=contractor_id,
                amount=str(payment_data.amount),  # строка как требует API
                status=payment_status,
                purpose=payment_data.purpose,
                services_list=services_list,
                bank_details_kind=bank_details_kind,
                bank_details=bank_details_response,
                created_at=created_at or datetime.utcnow(),
                updated_at=updated_at,
                paid_at=paid_at
            )

        except Exception as pay_e:
            print(f"❌ Ошибка создания платежа: {pay_e}")
            raise HTTPException(status_code=400, detail=f"Ошибка создания платежа: {str(pay_e)}")

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Внутренняя ошибка сервера: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")