import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
url = os.environ.get("WHATSAPP_SESSIONS_MONGO_URL", "").strip()
print("URL set:", bool(url), "| starts with mongodb:", url.startswith("mongodb"))
if not url:
    raise SystemExit(1)

client = MongoClient(url, serverSelectionTimeoutMS=10000)
db = client["lrasa_analytics"]
try:
    # list_collection_names forces a server round-trip
    names = db.list_collection_names()
    print("Connected OK. Collections:", names)
    col = db.sent_reminders
    print("sent_reminders count:", col.count_documents({}))
    print("indexes:", list(col.index_information().keys()))
except Exception as e:
    print("CONNECTION FAILED:", type(e).__name__, e)
