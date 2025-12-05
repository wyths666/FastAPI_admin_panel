import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(asctime)s - %(name)s - (Line: %(lineno)d) - [%(filename)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

bot_logger = logging.getLogger('bot')
bot_1_logger = logging.getLogger('bot_1')
api_logger = logging.getLogger('api')
