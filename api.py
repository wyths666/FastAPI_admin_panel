import uvicorn

from api.router.user import router as user
from core.api import app
from core.logger import api_logger as logger

app.include_router(router=user)


if __name__ == "__main__":
    try:
        uvicorn.run(
            app=app,
            host="0.0.0.0",
            port=9000
        )
    except KeyboardInterrupt:
        logger.info('Exit')
