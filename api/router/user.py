from fastapi import APIRouter, Depends

from api.schemas.response import ResponseBase
from api.schemas.user import User
from db.psql.models import models as psql
from utils.api import auth_by_token

router = APIRouter(
    tags=["User"],
    prefix='/user'
)


@router.post("")
async def post_user(data: User = Depends(), auth: bool = Depends(auth_by_token)) -> ResponseBase:
    """
        Create user
    :param data: User
    :param auth: Authentication by token
    :return: User
    """
    await psql.User.create(
        tg_id=data.tg_id,
        full_name=data.full_name,
        username=data.username
    )

    return ResponseBase(success=True)
