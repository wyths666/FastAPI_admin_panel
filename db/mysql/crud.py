import aiomysql
from contextlib import asynccontextmanager
from config import cnf


@asynccontextmanager
async def get_connection():
    conn = await aiomysql.connect(
        host=cnf.mysql.HOST,
        port=cnf.mysql.PORT,
        user=cnf.mysql.USER,
        password=cnf.mysql.PASSWORD,
        db=cnf.mysql.DATABASE,
        charset='utf8mb4',
        autocommit=True
    )
    try:
        yield conn
    finally:
        conn.close()


async def init_mysql():
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW TABLES LIKE 'oc_qrcode'")
            exists = await cur.fetchone()
            if not exists:
                raise Exception("Таблица oc_qrcode не найдена в базе MySQL!")


async def get_and_delete_code(code_text: str):
    """
    Пытается найти код и сразу удалить его (атомарно).
    Возвращает True, если код существовал и удалён.
    """
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            # Сначала проверяем наличие
            await cur.execute("SELECT code_text FROM oc_qrcode WHERE code_text = %s", (code_text,))
            exists = await cur.fetchone()

            if not exists:
                return False

            # Удаляем код
            await cur.execute("DELETE FROM oc_qrcode WHERE code_text = %s", (code_text,))

            return True
