from pathlib import Path
from typing import List

from aiogram.types import BotCommand
from pydantic import field_validator
from pydantic_settings import BaseSettings


class ProjConfig(BaseSettings):
    DATA_DIR: Path = Path(__file__).parent / 'data'

    class Config:
        env_prefix = 'PROJ_'
        env_file = '.env'
        extra = 'ignore'


class BotConfig(BaseSettings):
    TOKEN: str
    ADMINS: List[int] | None = []
    COMMANDS: List[BotCommand] = [
        BotCommand(
            command='start',
            description='Меню'
        )
    ]
    ADMIN_COMMANDS: List[BotCommand] = [
        BotCommand(
            command='admin',
            description='Админ-Панель'
        )
    ]

    class Config:
        env_prefix = 'BOT_'
        env_file = '.env'
        extra = 'ignore'

    @field_validator('ADMINS', mode='before')
    def split_admins(cls, v):
        try:
            return [int(admin_id) for admin_id in str(v).split(',')]

        except Exception:
            raise ValueError('ADMINS value must be int,int,int')


class PostgresConfig(BaseSettings):
    NAME: str
    HOST: str
    PORT: int
    PASSWORD: str
    USER: str

    @property
    def URL(self) -> str:
        return f"postgresql+asyncpg://{self.USER}:{self.PASSWORD}@{self.HOST}:{self.PORT}/{self.NAME}"

    class Config:
        env_prefix = 'POSTGRES_'
        env_file = '.env'
        extra = 'ignore'


class RedisConfig(BaseSettings):
    NAME: str
    HOST: str
    PORT: int
    PASSWORD: str
    USER: str

    class Config:
        env_prefix = 'REDIS_'
        env_file = '.env'
        extra = 'ignore'

    @property
    def URL(self) -> str:
        return f"redis://{self.USER}:{self.PASSWORD}@{self.HOST}:{self.PORT}/{self.NAME}"


class MongoConfig(BaseSettings):
    NAME: str
    PORT: int
    HOST: str

    class Config:
        env_prefix = 'MONGO_'
        env_file = '.env'
        extra = 'ignore'

    @property
    def URL(self) -> str:
        return f"mongodb://{self.HOST}:{self.PORT}/{self.NAME}"


class ApiConfig(BaseSettings):
    TOKEN: str

    class Config:
        env_prefix = 'API_'
        env_file = '.env'
        extra = 'ignore'


class MysqlConfig(BaseSettings):
    HOST: str
    PORT: int = 3306
    USER: str
    PASSWORD: str
    DATABASE: str

    class Config:
        env_prefix = 'MYSQL_'
        env_file = '.env'
        extra = 'ignore'

class Config:
    psql = PostgresConfig()
    redis = RedisConfig()
    mongo = MongoConfig()
    api = ApiConfig()
    bot = BotConfig()
    proj = ProjConfig()
    mysql = MysqlConfig()


cnf = Config()
