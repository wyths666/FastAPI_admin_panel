import asyncio
from datetime import datetime
from copy import deepcopy
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from db.beanie.models.models import Claim

MONGO_NAME="pure_bot"
MONGO_HOST="mongodb"
MONGO_PORT=27017
MONGO_URL= f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_NAME}"


async def clone_claims(
    source_claim_id: str,
    copies: int = 1000,
):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[MONGO_NAME]

    await init_beanie(database=db, document_models=[Claim], allow_index_dropping=True)

    source = await Claim.get(claim_id=source_claim_id)
    if not source:
        raise ValueError("Source claim not found")

    source_data = source.dict()
    source_data.pop("id", None)

    docs: list[Claim] = []

    next_claim_id = int(await Claim.generate_next_claim_id())

    for i in range(copies):
        data = deepcopy(source_data)

        data["claim_id"] = f"{next_claim_id + i:06d}"
        data["created_at"] = datetime.now()
        data["updated_at"] = datetime.now()

        docs.append(Claim(**data))

    await Claim.insert_many(docs)

    print(f"✅ Created {copies} claims")

async def create_indexes():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[MONGO_NAME]

    await init_beanie(database=db, document_models=[Claim], allow_index_dropping=True)
    print("OK")

if __name__ == "__main__":
    # asyncio.run(
    #     clone_claims(
    #         source_claim_id="000001",
    #         copies=1000,
    #     )
    # )
    asyncio.run(create_indexes())