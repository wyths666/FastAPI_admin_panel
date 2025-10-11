import logging
from logging import Logger, getLogger, Formatter, StreamHandler, INFO


def setting_logger(logger: Logger) -> Logger:
    """
        Setting logger. Add handlers formatter etc.
    :param logger: Logger
    """
    # Create formatter
    formatter = Formatter(
        datefmt='%Y-%m-%d %H:%M:%S',
        fmt="%(levelname)s - %(asctime)s - %(name)s - (Line: %(lineno)d) - [%(filename)s]: %(message)s"
    )

    # Create stream handler
    stream_handler = StreamHandler(
        # stream=sys.stdout
    )
    stream_handler.setFormatter(formatter)

    # Add handlers to logger
    logger.handlers = [stream_handler]

    logger.setLevel(INFO)

    return logger


# Create loggers
bot_logger = setting_logger(
    logger=getLogger('bot')
)
api_logger = setting_logger(
    logger=getLogger('api')
)

logging.basicConfig(level=INFO)
