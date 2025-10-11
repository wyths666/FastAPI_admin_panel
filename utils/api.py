import secrets

from fastapi import HTTPException, status, Header

from config import cnf


async def auth_by_token(token: str = Header(alias='x-auth-token')) -> bool:
    """
        Auth request by token
    :param token: Token form request header
    """
    if not secrets.compare_digest(token, cnf.api.TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    return True
