import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
url = os.environ.get("WHATSAPP_SESSIONS_MONGO_URL", "").strip()
client = MongoClient(url, serverSelectionTimeoutMS=10000)

print("=== ALL DATABASES on this cluster ===")
for db_name in client.list_database_names():
    db = client[db_name]
    cols = db.list_collection_names()
    print(f"  DB: {db_name!r}  collections: {cols}")
    if "sent_reminders" in cols:
        print(f"    -> sent_reminders count: {db.sent_reminders.count_documents({})}")
