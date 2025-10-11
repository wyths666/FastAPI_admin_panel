from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import cnf

engine = create_async_engine(
    url=cnf.psql.URL,
    # echo=True,
    pool_size=50,
    max_overflow=20
)

postgres_conn = async_sessionmaker(engine)


class Base(DeclarativeBase):
    pass
