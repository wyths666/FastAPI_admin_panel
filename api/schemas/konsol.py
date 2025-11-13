from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from decimal import Decimal


# === Схемы для создания платежа ===
class CreatePaymentRequest(BaseModel):
    contractor_id: str
    amount: Decimal = Field(..., description="Сумма платежа (например: 100.00)")
    purpose: str = Field(..., description="Назначение платежа")

    # Реквизиты (только одно поле заполняется в зависимости от способа)
    phone_number: Optional[str] = Field(None, description="Телефон для СБП")
    fps_bank_member_id: Optional[str] = Field(None, description="ID банка СБП (из справочника)")
    card_number: Optional[str] = Field(None, description="Номер карты")

    # Связь с нашей системой
    claim_id: str = Field(..., description="ID заявки")
    user_id: int = Field(..., description="ID пользователя (tg_id)")

    def model_dump(self, **kwargs):
        # Возвращаем только заполненные поля
        data = super().model_dump(exclude_unset=True, **kwargs)
        return data


# === Схемы для ответа от API ===
class PaymentResponse(BaseModel):
    id: str
    contractor_id: str
    amount: str  # строка, как в API
    status: str  # created, manualpay, executed, failed, nalog_unbound
    purpose: str
    services_list: List[Dict[str, Any]]
    bank_details_kind: str  # "fps", "card", "bank_account"
    bank_details: Dict[str, Any]  # зависит от kind
    created_at: datetime
    updated_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None


class FpsBankMemberResponse(BaseModel):
    id: str
    name: str
    bic: str


# === Схемы для списка платежей (если понадобится) ===
class PaymentsListResponse(BaseModel):
    items: List[PaymentResponse]
    total: int
    page: int
    per_page: int


class PaymentCreateRequest(BaseModel):
    payment_type: str = Field(..., description="Тип выплаты: 'card' или 'fps'")
    amount: Decimal = Field(..., gt=0, description="Сумма выплаты")
    phone: Optional[str] = Field(None, description="Телефон для СБП")
    bank_member_id: Optional[str] = Field(None, description="ID банка для СБП")
    card_number: Optional[str] = Field(None, description="Номер карты")
    first_name: str = Field(..., description="Имя получателя")
    last_name: str = Field(..., description="Фамилия получателя")
    purpose: str = Field(default="Выплата", description="Назначение платежа")

class HandPaymentResponse(BaseModel):
    payment_id: str
    konsol_id: Optional[str]
    contractor_id: str
    amount: Decimal
    status: str
    payment_type: str
    purpose: str
    created_at: datetime
    message: str

class BankInfo(BaseModel):
    id: str
    name: str