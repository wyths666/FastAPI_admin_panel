from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.logger import api_logger as logger


@asynccontextmanager
async def fastapi_lifespan(app: FastAPI) -> None:
    """
        Init project
    :param app: FastAPI
    :return:
    """
    logger.info('=== App started ===')

    yield

    logger.info('=== App stopped ===')


app = FastAPI(
    title="api",
    lifespan=fastapi_lifespan
)
