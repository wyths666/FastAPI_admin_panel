from motor.motor_asyncio import AsyncIOMotorClient

from config import cnf


client: AsyncIOMotorClient = AsyncIOMotorClient(cnf.mongo.URL)