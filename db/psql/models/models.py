from typing import TypeVar, Generic, Sequence, Optional

from sqlalchemy import ForeignKey, CheckConstraint, func, BigInteger
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Mapped, selectinload, load_only, relationship, validates
from sqlalchemy.sql import select, update as sqlalchemy_update

from core.psql import postgres_conn as conn, Base
from db.psql.models.enum import *
from db.psql.models.columns import *

T = TypeVar("T")


class ModelAdmin(Generic[T]):
    @classmethod
    async def create(cls, **kwargs) -> T:
        """
            Создает новый объект и возвращает его.
        :param kwargs: Поля и значения для объекта.
        :return: Созданный объект.
        """

        async with conn() as session:
            obj = cls(**kwargs)
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj

    @classmethod
    async def add(cls, **kwargs) -> None:
        """
            Создает новый объект.
        :param kwargs: Поля и значения для объекта.
        """

        async with conn() as session:
            session.add(cls(**kwargs))
            await session.commit()

    async def update(self, **kwargs) -> None:
        """
            Обновляет текущий объект.
        :param kwargs: Поля и значения, которые надо поменять.
        """
        async with conn() as session:
            await session.execute(
                sqlalchemy_update(self.__class__), [{"id": self.id, **kwargs}]
            )
            await session.commit()

    async def delete(self) -> None:
        """
        # Удаляет объект.
        """
        async with conn() as session:
            await session.delete(self)
            await session.commit()

    @classmethod
    async def get(cls, select_in_load: str | None = None, **kwargs) -> T:
        """
            Возвращает одну запись, которая удовлетворяет введенным параметрам.
        :param select_in_load: Загрузить сразу связанную модель.
        :param kwargs: Поля и значения.
        :return: Объект или вызовет исключение DoesNotExists.
        """

        params = [getattr(cls, key) == val for key, val in kwargs.items()]
        query = select(cls).where(*params)

        if select_in_load:
            query.options(selectinload(getattr(cls, select_in_load)))

        try:
            async with conn() as session:
                results = await session.execute(query)
                (result,) = results.one()
                return result
        except NoResultFound:
            return None

    @classmethod
    async def check(cls, **kwargs) -> int | None:
        """
            Проверить наличие записи в таблице не тяжелым запросом и вернуть только его id
        :param kwargs: Id of obj
        """
        params = [getattr(cls, key) == val for key, val in kwargs.items()]
        query = select(cls.id).where(*params)

        try:
            async with conn() as session:
                results = await session.execute(query)
                (result,) = results.one()
                return result
        except NoResultFound:
            return None

    @classmethod
    async def filter(cls, select_in_load: str | None = None, **kwargs) -> Sequence[T]:
        """
            Возвращает все записи, которые удовлетворяют введенным параметрам.
        :param select_in_load: Загрузить сразу связанную модель.
        :param kwargs: Поля и значения.
        :return: Перечень записей.
        """

        params = [getattr(cls, key) == val for key, val in kwargs.items()]
        query = select(cls).where(*params)

        if select_in_load:
            query.options(selectinload(getattr(cls, select_in_load)))

        try:
            async with conn() as session:
                results = await session.execute(query)
                return results.scalars().all()
        except NoResultFound:
            return ()

    @classmethod
    async def all(cls, select_in_load: str = None, values: list[str] = None) -> Sequence[T]:
        """
            Получение всех записей
        :param select_in_load: Загрузить сразу связанную модель.
        :param values: Список полей, которые надо вернуть, если нет, то все (default None).
        """

        if values and isinstance(values, list):
            # Определенные поля
            values = [getattr(cls, val) for val in values if isinstance(val, str)]
            query = select(cls).options(load_only(*values))
        else:
            # Все поля
            query = select(cls)

        if select_in_load:
            query.options(selectinload(getattr(cls, select_in_load)))

        async with conn() as session:
            result = await session.execute(query)
            return result.scalars().all()


class User(Base, ModelAdmin):
    __tablename__ = 'users'

    id: Mapped[intpk]
    tg_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True
    )
    full_name: Mapped[str_128]
    username: Mapped[str_32 | None]
    created_at: Mapped[created_at | None]
