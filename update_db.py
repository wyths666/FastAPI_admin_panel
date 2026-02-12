import asyncio
from utils.database import init_database_bot1


async def update_db():
    db = await init_database_bot1()
    pipeline = [
        {"$sort": {"date": 1}},
        {"$group": {
            "_id": "$from_id",
            "last_message_date": {"$last": "$date"},
            "last_message_text": {"$last": "$message_object"},
            "last_message_type": {"$last": "$file_type"},
            "message_count": {"$sum": 1},
            "unread_count": {
                "$sum": {
                    "$cond": [
                        {"$and": [
                            {"$eq": ["$checked", "0"]},
                            {"$eq": ["$from_operator", "0"]}
                        ]},
                        1,
                        0
                    ]
                }
            }
        }}
    ]

    data = await db.messages.aggregate(pipeline).to_list(None)

    bulk = []
    for d in data:
        user = await db.users.find_one({"id": d["_id"]}) or {}
        bulk.append({
            "user_id": d["_id"],
            "username": user.get("username", ""),
            "full_name": user.get("full_name", ""),
            "banned": user.get("banned", "0"),
            "last_message_text": d.get("last_message_text", ""),
            "last_message_date": d["last_message_date"],
            "last_message_type": d.get("last_message_type", "text"),
            "message_count": d["message_count"],
            "unread_count": d["unread_count"]
        })

    if bulk:
        await db.chat_dialogs.insert_many(bulk)

    print("✅ chat_dialogs создана")

if __name__ == "__main__":
    asyncio.run(update_db())