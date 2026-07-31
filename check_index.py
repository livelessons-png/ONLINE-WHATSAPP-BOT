import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
url = os.environ.get("WHATSAPP_SESSIONS_MONGO_URL")
if not url:
    print("ERROR: WHATSAPP_SESSIONS_MONGO_URL is not set in .env")
    raise SystemExit(1)

client = MongoClient(url, serverSelectionTimeoutMS=10000)
db = client["lrasa_analytics"]
col = db.sent_reminders

print("=== 1. INDEXES on sent_reminders ===")
for name, spec in col.index_information().items():
    print(f"  {name}: keys={spec['key']} unique={spec.get('unique', False)}")

print("\n=== 2. DUPLICATE COUNTS (event_uid+phone+tier) ===")
dupes = list(col.aggregate([
    {"$group": {"_id": {"event_uid": "$event_uid", "phone": "$phone", "tier": "$tier"},
                "n": {"$sum": 1}, "ids": {"$push": "$_id"}}},
    {"$match": {"n": {"$gt": 1}}},
]))
if not dupes:
    print("  No duplicates. (good)")
else:
    for d in dupes:
        print(f"  key={d['_id']} count={d['n']}")
    print(f"\n  TOTAL duplicate groups: {len(dupes)}")
