from core.psql import postgres_conn, engine
from db.psql.models.models import Base


async def init_psql() -> bool:
    """
        Create all tables in db
    :return: True or False
    """
    async with postgres_conn() as s:
        # await s.run_sync(
        #     lambda s_value: Base.metadata.drop_all(
        #         bind=s_value.bind
        #     )
        # )

        await s.run_sync(
            lambda s_value: Base.metadata.create_all(
                bind=s_value.bind
            )
        )
        return True
