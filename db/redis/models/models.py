from typing import TypeVar, Generic, Sequence

from aredis_om import HashModel, Field

from core.redis import redis_conn as conn

T = TypeVar("T")


class ModelAdmin(HashModel, Generic[T]):
    @classmethod
    async def create(cls, ttl: int | None = None, **kwargs) -> T:
        """
            Создать новые объект в бд
        :param ttl: Время жизни нового объекта
        :return: Созданный объект
        """
        model = cls(**kwargs)
        model = await model.save()

        if ttl:
            await model.expire(ttl)

        return model

    async def update(self, **kwargs) -> None:
        """
            Обновить текущий объект в БД
        :param kwargs: Ячейки, которые вам нужно обновить
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

        await self.save()

    async def delete(self) -> None:
        """
            Удалить текущий объект в БД
        """
        await super().delete(self.pk)

    @classmethod
    async def get(cls, pk: str) -> T:
        """
            Получите один объект по фильтрам
        :param pk: PK
        """
        try:
            return await super().get(pk)

        except Exception as e:
            return None

    @classmethod
    async def filter(cls, **kwargs) -> Sequence[T]:
        """
            Получить список объектов от DB по фильтрам
        """
        conditions = [getattr(cls, key) == value for key, value in kwargs.items()]
        return await cls.find(*conditions).all()

    async def set_ttl(self, ttl: int) -> bool:
        """
            Установите TTL для объекта
        :param ttl: TTL для объекта
        """
        return await self.expire(ttl)

    @classmethod
    async def all(cls):
        """
            Взять все ключи объектов класса
        """
        return await super().all_pks()


class User(ModelAdmin):
    tg_id: int = Field(index=True)
    username: str

    class Meta:
        database = conn
