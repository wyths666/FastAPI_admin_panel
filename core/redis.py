from aredis_om import get_redis_connection

from config import cnf


redis_conn = get_redis_connection(
    url=cnf.redis.URL,
    decode_responses=True,
    encoding='utf-8',
    max_connections=50,
    health_check_interval=30
)
