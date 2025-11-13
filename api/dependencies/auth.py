from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from db.beanie.models import Administrators

security = HTTPBearer()


async def get_current_admin(
        credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Administrators:
    token = credentials.credentials

    # Ищем администратора по session_token
    admin = await Administrators.find_one(
        Administrators.session_token == token,
        Administrators.is_active == True
    )

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return admin


# Дополнительная зависимость для проверки прав
async def get_current_active_admin(
        current_admin: Administrators = Depends(get_current_admin)
) -> Administrators:
    if not current_admin.is_active:
        raise HTTPException(status_code=400, detail="Inactive admin")
    return current_admin