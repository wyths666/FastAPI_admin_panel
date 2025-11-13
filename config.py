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
    GROUP_ID: int
    CHANNEL_USERNAME: str
    SUPPORT: str
    COMMANDS: List[BotCommand] = [
        BotCommand(
            command='start',
            description='Запуск'
        ),
    BotCommand(command="help", description="Техническая поддержка")
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


class Bot1Config(BaseSettings):
    TOKEN: str
    ADMINS: List[int] | None = []
    COMMANDS: List[BotCommand] = [
        BotCommand(
            command='start',
            description='Запуск'
        )]
    ADMIN_COMMANDS: List[BotCommand] = [
        BotCommand(
            command='admin',
            description='Админ-Панель'
        )
    ]

    class Config:
        env_prefix = 'BOT1_'
        env_file = '.env'
        extra = 'ignore'

    @field_validator('ADMINS', mode='before')
    def split_admins(cls, v):
        try:
            return [int(admin_id) for admin_id in str(v).split(',')]

        except Exception:
            raise ValueError('ADMINS value must be int,int,int')


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


class MongoBot1Config(BaseSettings):
    NAME: str
    PORT: int
    HOST: str

    class Config:
        env_prefix = 'MONGO_BOT1_'
        env_file = '.env'
        extra = 'ignore'

    @property
    def URL(self) -> str:
        return f"mongodb://{self.HOST}:{self.PORT}/{self.NAME}"


class MysqlConfig(BaseSettings):
    HOST: str
    PORT: int = 3306
    USER: str
    PASSWORD: str
    DATABASE: str

    @property
    def URL(self) -> str:
        return f"mysql+aiomysql://{self.USER}:{self.PASSWORD}@{self.HOST}:{self.PORT}/{self.DATABASE}"

    class Config:
        env_prefix = 'MYSQL_'
        env_file = '.env'
        extra = 'ignore'

class KonsolConfig(BaseSettings):
    TOKEN: str
    BASE_URL: str = "https://swagger-payments.konsol.pro"
    TIMEOUT: int = 30

    class Config:
        env_prefix = 'KONSOL_'
        env_file = '.env'
        extra = 'ignore'


class Config:
    mongo = MongoConfig()
    mongo_bot1 = MongoBot1Config()
    bot = BotConfig()
    bot1 = Bot1Config()
    proj = ProjConfig()
    mysql = MysqlConfig()
    konsol = KonsolConfig()


cnf = Config()
