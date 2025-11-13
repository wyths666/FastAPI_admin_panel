from pydantic import BaseModel
from datetime import datetime

class LoginRequest(BaseModel):
    login: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin_id: int
    login: str

class AdminResponse(BaseModel):
    admin_id: int
    login: str
    is_active: bool
    created_at: datetime

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str