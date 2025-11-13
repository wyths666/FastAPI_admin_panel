from pymongo import MongoClient
from collections import defaultdict


def analyze_all_collections():
    """Проанализировать дубликаты во всех коллекциях"""
    client = MongoClient('mongodb://localhost:27017')
    db = client['wb']

    collections = ['users', 'products', 'messages']

    for collection_name in collections:
        print(f"\n📊 АНАЛИЗ КОЛЛЕКЦИИ: {collection_name.upper()}")
        print("=" * 50)

        collection = db[collection_name]

        # Для каждой коллекции свой ключ
        if collection_name == 'users':
            group_field = 'id'
        elif collection_name == 'products':
            group_field = 'id'
        elif collection_name == 'messages':
            group_field = 'id'

        pipeline = [
            {"$group": {
                "_id": f"${group_field}",
                "count": {"$sum": 1},
                "docs": {"$push": "$$ROOT"}
            }},
            {"$match": {"count": {"$gt": 1}}},
            {"$sort": {"count": -1}}
        ]

        duplicates = list(collection.aggregate(pipeline))

        print(f"Найдено дубликатов: {len(duplicates)}")

        # Показать первые 5 для примера
        for i, dup in enumerate(duplicates[:5]):
            print(f"  {i + 1}. id {dup['_id']}: {dup['count']} записей")

            # Показать различия если есть
            first_doc = dup['docs'][0]
            different_fields = []

            for doc in dup['docs'][1:]:
                for key in doc:
                    if key != '_id' and doc.get(key) != first_doc.get(key):
                        if key not in different_fields:
                            different_fields.append(key)

            if different_fields:
                print(f"     Различающиеся поля: {different_fields}")


def safe_cleanup_all_collections():
    """Безопасная очистка дубликатов во всех коллекциях"""
    client = MongoClient('mongodb://localhost:27017')
    db = client['wb']

    collections_config = {
        'users': {'id_field': 'id', 'strategy': 'keep_oldest'},
        'products': {'id_field': 'id', 'strategy': 'keep_oldest'},
        'messages': {'id_field': 'id', 'strategy': 'keep_oldest'}
    }

    total_cleaned = 0

    for collection_name, config in collections_config.items():
        print(f"\n🧹 ОЧИСТКА: {collection_name.upper()}")
        print("-" * 40)

        collection = db[collection_name]
        id_field = config['id_field']

        # Найти дубликаты
        pipeline = [
            {"$group": {
                "_id": f"${id_field}",
                "docs": {"$push": {"_id": "$_id", "mongo_id": "$_id"}},
                "count": {"$sum": 1}
            }},
            {"$match": {"count": {"$gt": 1}}}
        ]

        duplicates = list(collection.aggregate(pipeline))

        if not duplicates:
            print("✅ Дубликатов не найдено")
            continue

        print(f"Найдено групп дубликатов: {len(duplicates)}")

        cleaned_count = 0
        for dup in duplicates:
            # Стратегия: оставляем самый старый документ (по _id)
            docs_sorted = sorted(dup['docs'], key=lambda x: x['mongo_id'])
            keeper_id = docs_sorted[0]['_id']  # Самый старый
            delete_ids = [doc['_id'] for doc in docs_sorted[1:]]  # Остальные

            result = collection.delete_many({"_id": {"$in": delete_ids}})
            cleaned_count += result.deleted_count

            if result.deleted_count > 0:
                print(f"✅ id {dup['_id']}: удалено {result.deleted_count} дубликатов")

        total_cleaned += cleaned_count
        print(f"🎯 В {collection_name} удалено: {cleaned_count} записей")

    print(f"\n🎉 ОБЩИЙ РЕЗУЛЬТАТ:")
    print(f"Всего удалено дубликатов: {total_cleaned}")

    # Финальная проверка
    print(f"\n🔍 ФИНАЛЬНАЯ ПРОВЕРКА:")
    for collection_name in collections_config.keys():
        pipeline = [
            {"$group": {"_id": f"${collections_config[collection_name]['id_field']}", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}}
        ]
        remaining = list(db[collection_name].aggregate(pipeline))
        print(f"{collection_name}: осталось дубликатов - {len(remaining)}")



if __name__ == "__main__":
    analyze_all_collections()
    safe_cleanup_all_collections()

