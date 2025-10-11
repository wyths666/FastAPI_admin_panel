from pydantic import BaseModel


class User(BaseModel):
    tg_id: int
    full_name: str
    username: str
