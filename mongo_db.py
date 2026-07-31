"""
MongoDB helper module for MIVA WhatsApp Bot.
Replaces all SQLite operations with MongoDB Atlas.
Uses WHATSAPP_SESSIONS_MONGO_URL from environment.
"""
import os
import datetime
from bson.objectid import ObjectId
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

MONGO_URL = os.environ.get("WHATSAPP_SESSIONS_MONGO_URL")
_client = None
_db = None


def get_client():
    global _client
    if _client is None and MONGO_URL:
        _client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    return _client


def get_db():
    global _db
    if _db is None and get_client() is not None:
        _db = get_client()["lrasa_analytics"]
        _ensure_indexes()
    return _db


def _ensure_indexes():
    """Create indexes for common query patterns."""
    db = _db
    if db is None:
        return
    try:
        db.app_settings.create_index("key", unique=True)
        db.contact_aliases.create_index("alias_id", unique=True)
        db.delivery_routes.create_index("identity_key", unique=True)
        db.consented_users.create_index("phone", unique=True)
        db.chat_history.create_index([("phone", ASCENDING), ("timestamp", ASCENDING)])
        db.interactions.create_index([("timestamp", DESCENDING)])
        db.sent_reminders.create_index([("phone", ASCENDING), ("sent_at", DESCENDING)])
        # ✅ FIX: Enforce UNIQUE constraint on event_uid + phone + tier combination
        db.sent_reminders.create_index(
            [("event_uid", ASCENDING), ("phone", ASCENDING), ("tier", ASCENDING)],
            unique=True
        )
        db.pending_setting_changes.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    except Exception as e:
        print(f"Index creation warning: {e}")


# ==========================================
# APP SETTINGS
# ==========================================
def get_setting(key, default=""):
    db = get_db()
    if db is None:
        return default
    doc = db.app_settings.find_one({"key": key})
    if doc and doc.get("value"):
        return doc["value"]
    return default


def set_setting(key, value, updated_by="system"):
    db = get_db()
    if db is None:
        return
    db.app_settings.update_one(
        {"key": key},
        {"$set": {"value": str(value), "updated_by": updated_by,
                  "updated_at": datetime.datetime.now().isoformat()}},
        upsert=True,
    )


def get_all_settings():
    db = get_db()
    if db is None:
        return []
    return list(db.app_settings.find({}, {"_id": 0}).sort("key", ASCENDING))


# ==========================================
# CONTACT ALIASES
# ==========================================
def get_mapped_phone_for_alias(alias_id):
    db = get_db()
    if db is None:
        return ""
    doc = db.contact_aliases.find_one({"alias_id": str(alias_id).strip()})
    return doc["phone"] if doc and doc.get("phone") else ""


def upsert_contact_alias(alias_id, phone, name=""):
    db = get_db()
    if db is None:
        return
    mapped_phone = "".join(filter(str.isdigit, str(phone)))
    alias = str(alias_id or "").strip()
    if not alias or not mapped_phone:
        return
    db.contact_aliases.update_one(
        {"alias_id": alias},
        {"$set": {"phone": mapped_phone, "name": str(name or "").strip(),
                  "updated_at": datetime.datetime.now().isoformat()}},
        upsert=True,
    )


# ==========================================
# DELIVERY ROUTES
# ==========================================
def remember_successful_delivery_route(identity_value, chat_id):
    db = get_db()
    if db is None:
        return
    chat = str(chat_id or "").strip()
    raw = str(identity_value or "").strip()
    if not raw or not chat:
        return
    if chat.lower().endswith("@lid"):
        return
    keys = [f"raw:{raw.lower()}"]
    normalized = "".join(filter(str.isdigit, raw))
    if normalized:
        keys.append(f"num:{normalized}")
    for identity_key in keys:
        db.delivery_routes.update_one(
            {"identity_key": identity_key},
            {"$set": {"chat_id": chat, "updated_at": datetime.datetime.now().isoformat()}},
            upsert=True,
        )


def get_preferred_delivery_route(identity_value):
    db = get_db()
    if db is None:
        return ""
    raw = str(identity_value or "").strip()
    if not raw:
        return ""
    keys = [f"raw:{raw.lower()}"]
    normalized = "".join(filter(str.isdigit, raw))
    if normalized:
        keys.append(f"num:{normalized}")
    for identity_key in keys:
        doc = db.delivery_routes.find_one({"identity_key": identity_key})
        if doc and doc.get("chat_id"):
            candidate = doc["chat_id"]
            if not candidate.lower().endswith("@lid"):
                return candidate
    return ""


# ==========================================
# CONSENTED USERS
# ==========================================
def has_user_consented(phone):
    db = get_db()
    if db is None:
        return False
    return db.consented_users.find_one({"phone": str(phone).strip()}) is not None


def mark_user_consented(phone):
    db = get_db()
    if db is None:
        return
    db.consented_users.update_one(
        {"phone": str(phone).strip()},
        {"$setOnInsert": {"phone": str(phone).strip(),
                          "consented_at": datetime.datetime.now().isoformat()}},
        upsert=True,
    )


# ==========================================
# CHAT HISTORY
# ==========================================
def save_chat_turn(phone, role, content):
    db = get_db()
    if db is None:
        return
    db.chat_history.insert_one({
        "phone": str(phone),
        "role": str(role),
        "content": str(content),
        "timestamp": datetime.datetime.now().isoformat(),
    })


def get_recent_history(phone):
    db = get_db()
    if db is None:
        return []
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat()
    docs = list(db.chat_history.find(
        {"phone": str(phone), "timestamp": {"$gte": cutoff}},
        {"_id": 0, "role": 1, "content": 1},
    ).sort("_id", ASCENDING))
    return [{"role": d["role"], "content": d["content"]} for d in docs]


# ==========================================
# INTERACTIONS
# ==========================================
def log_interaction(phone, query, response):
    db = get_db()
    if db is None:
        return
    db.interactions.insert_one({
        "timestamp": datetime.datetime.now().isoformat(),
        "phone": str(phone),
        "query": str(query),
        "response": str(response),
    })


# ==========================================
# SENT REMINDERS
# ==========================================
def get_latest_sent_reminder(phone):
    db = get_db()
    if db is None:
        return None
    doc = db.sent_reminders.find_one(
        {"phone": str(phone)},
        sort=[("sent_at", DESCENDING)],
    )
    return doc


def mark_reminder_response(phone):
    db = get_db()
    if db is None:
        return
    doc = db.sent_reminders.find_one(
        {"phone": str(phone)},
        sort=[("sent_at", DESCENDING)],
    )
    if doc:
        db.sent_reminders.update_one(
            {"_id": doc["_id"]},
            {"$set": {"is_response": 1},
             "$inc": {"questions_count": 1}},
        )


def get_latest_event_uid(phone):
    db = get_db()
    if db is None:
        return None
    doc = db.sent_reminders.find_one(
        {"phone": str(phone)},
        sort=[("sent_at", DESCENDING)],
    )
    return doc["_id"] if doc else None


def confirm_reminder(event_id, phone):
    db = get_db()
    if db is None:
        return
    query_id = ObjectId(event_id) if isinstance(event_id, str) and len(event_id) == 24 else event_id
    db.sent_reminders.update_one(
        {"_id": query_id, "phone": str(phone)},
        {"$set": {"is_confirmed": 1, "is_escalated": 0}},
    )


def escalate_reminder(event_id, phone):
    db = get_db()
    if db is None:
        return
    query_id = ObjectId(event_id) if isinstance(event_id, str) and len(event_id) == 24 else event_id
    db.sent_reminders.update_one(
        {"_id": query_id, "phone": str(phone)},
        {"$set": {"is_confirmed": 0, "is_escalated": 1}},
    )


def escalate_non_response(phone):
    db = get_db()
    if db is None:
        return None
    doc = db.sent_reminders.find_one(
        {"phone": str(phone)},
        sort=[("sent_at", DESCENDING)],
    )
    if doc and not doc.get("is_confirmed") and not doc.get("is_escalated"):
        db.sent_reminders.update_one(
            {"_id": doc["_id"]},
            {"$set": {"is_escalated": 1}},
        )
        return doc
    return None


def insert_sent_reminder(phone, tier="4_HOURS", status="delivered", event_uid="", course_code="", ai_confidence=None, event_id=""):
    """Inserts a general reminder with support for both event_uid and event_id kwargs."""
    db = get_db()
    if db is None:
        return None

    # ✅ Accept both event_id and event_uid kwarg variations seamlessly
    actual_uid = str(event_uid or event_id or "")

    # ✅ Direct check before insert as a primary safeguard against duplicates
    if actual_uid and has_reminder_been_sent(actual_uid, phone, tier):
        raise DuplicateKeyError(f"Duplicate reminder: {actual_uid} for {phone} ({tier}) already sent.")

    result = db.sent_reminders.insert_one({
        "event_uid": actual_uid,
        "course_code": str(course_code),
        "phone": str(phone),
        "tier": tier,
        "status": status,
        "is_confirmed": 0,
        "is_escalated": 0,
        "is_response": 0,
        "questions_count": 0,
        "ai_confidence": ai_confidence,
        "sent_at": datetime.datetime.now().isoformat(),
    })
    return result.inserted_id


# ==========================================
# PENDING SETTING CHANGES (settings approval)
# ==========================================
def add_pending_change(key, proposed_value, requested_by, reason=""):
    db = get_db()
    if db is None:
        return
    db.pending_setting_changes.insert_one({
        "key": key,
        "proposed_value": proposed_value,
        "requested_by": requested_by,
        "reason": reason,
        "status": "pending",
        "created_at": datetime.datetime.now().isoformat(),
        "reviewed_by": "",
        "reviewed_at": "",
        "review_note": "",
    })


def get_pending_changes():
    db = get_db()
    if db is None:
        return []
    return list(db.pending_setting_changes.find(
        {}, {"_id": 1, "key": 1, "proposed_value": 1, "requested_by": 1, "reason": 1, "status": 1, "created_at": 1, "reviewed_by": 1, "reviewed_at": 1, "review_note": 1}
    ).sort("_id", DESCENDING).limit(50))


def get_pending_change_by_id(change_id):
    db = get_db()
    if db is None:
        return None
    doc = db.pending_setting_changes.find_one({"_id": ObjectId(change_id), "status": "pending"})
    return doc


def approve_change(change_id, reviewed_by="admin"):
    db = get_db()
    if db is None:
        return
    doc = db.pending_setting_changes.find_one({"_id": ObjectId(change_id)})
    if not doc:
        return
    now_iso = datetime.datetime.now().isoformat()
    set_setting(doc["key"], doc["proposed_value"], reviewed_by)
    db.pending_setting_changes.update_one(
        {"_id": ObjectId(change_id)},
        {"$set": {"status": "approved", "reviewed_by": reviewed_by, "reviewed_at": now_iso}},
    )


def reject_change(change_id, reviewed_by="admin", review_note=""):
    db = get_db()
    if db is None:
        return
    db.pending_setting_changes.update_one(
        {"_id": ObjectId(change_id)},
        {"$set": {"status": "rejected", "reviewed_by": reviewed_by,
                  "reviewed_at": datetime.datetime.now().isoformat(), "review_note": review_note}},
    )


# ==========================================
# SENT REMINDERS (daemon-specific)
# ==========================================
def has_reminder_been_sent(event_uid, phone, tier):
    """Checks if a reminder for this event has already been processed (and recorded).

    Mirrors the unique index on (event_uid, phone, tier) so the daemon can
    explicitly look it up instead of relying on insert errors.
    """
    db = get_db()
    if db is None:
        return False
    doc = db.sent_reminders.find_one({
        "event_uid": str(event_uid),
        "phone": str(phone),
        "tier": str(tier),
    })
    return doc is not None


def record_sent_reminder(event_uid, phone, tier, course_code="", ai_confidence=None):
    """Records a daemon dispatch. Aligned with dashboard requirements.

    Only call this AFTER the WhatsApp message has actually been dispatched.
    Raises DuplicateKeyError if (event_uid, phone, tier) is already recorded.
    """
    db = get_db()
    if db is None:
        return None
    if has_reminder_been_sent(event_uid, phone, tier):
        raise DuplicateKeyError(f"Duplicate reminder: {event_uid} for {phone} ({tier}) already sent.")
    result = db.sent_reminders.insert_one({
        "event_uid": str(event_uid),
        "course_code": str(course_code),
        "phone": str(phone),
        "tier": str(tier),
        "status": "delivered",
        "sent_at": datetime.datetime.now().isoformat(),
        "is_confirmed": 0,
        "is_escalated": 0,
        "is_response": 0,
        "questions_count": 0,
        "ai_confidence": ai_confidence,
    })
    return result.inserted_id


def get_analytics_reminders(where_clause=None):
    db = get_db()
    if db is None:
        return []
    match_stage = where_clause if where_clause else {}
    pipeline = [
        {"$match": match_stage},
        {"$sort": {"sent_at": -1}},
        {"$limit": 50},
        {"$project": {"_id": 0, "event_uid": 1, "course_code": 1, "phone": 1, "tier": 1,
                       "sent_at": 1, "status": 1, "is_confirmed": 1,
                       "ai_confidence": 1}},
    ]
    return list(db.sent_reminders.aggregate(pipeline))


def get_tier_distribution(where_clause=None):
    db = get_db()
    if db is None:
        return []
    match_stage = where_clause if where_clause else {}
    pipeline = [
        {"$match": match_stage},
        {"$group": {"_id": "$tier", "qty": {"$sum": 1}}},
    ]
    return list(db.sent_reminders.aggregate(pipeline))


def get_analytics_metrics(where_clause=None):
    db = get_db()
    if db is None:
        return {}
    match_stage = where_clause if where_clause else {}
    pipeline = [
        {"$match": match_stage},
        {"$group": {
            "_id": None,
            "sent": {"$sum": 1},
            "delivered": {"$sum": {"$cond": [{"$in": ["$status", ["delivered", "read"]]}, 1, 0]}},
            "responses": {"$sum": {"$cond": [{"$eq": ["$is_response", 1]}, 1, 0]}},
            "questions": {"$sum": {"$ifNull": ["$questions_count", 0]}},
            "escalations": {"$sum": {"$cond": [{"$eq": ["$is_escalated", 1]}, 1, 0]}},
            "confirmations": {"$sum": {"$cond": [{"$eq": ["$is_confirmed", 1]}, 1, 0]}},
            "avg_conf": {"$avg": {"$ifNull": ["$ai_confidence", 0]}},
        }},
    ]
    results = list(db.sent_reminders.aggregate(pipeline))
    return results[0] if results else {}


def get_count(collection_name):
    db = get_db()
    if db is None:
        return 0
    return db[collection_name].count_documents({})