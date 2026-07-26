import os
import threading
import time
import datetime
import logging
import re
import requests
import pytz
from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from openai import OpenAI
from dotenv import load_dotenv
import mongo_db as db

# ========================================================
# 1. INITIALIZATION & GLOBAL CONFIGURATIONS
# ========================================================
load_dotenv()

db_lock = threading.Lock()
processed_messages = set()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [WEBHOOK] - %(levelname)s - %(message)s'
)

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

@app.before_request
def log_incoming_http_request():
    """Log inbound HTTP traffic for real-time monitoring."""
    try:
        path = request.path
        method = request.method
        remote = request.headers.get("X-Forwarded-For", request.remote_addr)
        app.logger.info(f"HTTP {method} {path} from {remote}")

        if path == "/webhook" and method == "POST":
            raw_json = request.get_json(silent=True)
            if isinstance(raw_json, dict):
                event_type = str(raw_json.get("event", "")).strip().lower()
                app.logger.info(f"Webhook event type: {event_type or 'N/A'}")
    except Exception as req_log_err:
        print(f"⚠️ Request logging failure: {req_log_err}", flush=True)

@app.route('/test')
def test_route():
    return "<h1>MIVA WAHA INTERACT ENGINE ONLINE</h1>"


# ==========================================
# 🔑 ENTERPRISE CREDENTIAL CONFIGURATIONS
# ==========================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FAQ_REPLY_MODEL = os.getenv("FAQ_REPLY_MODEL", "gpt-4o-mini")

# WAHA Local / External Configurations
WAHA_URL = os.getenv("WAHA_URL", "http://localhost:3001")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "MivaaroundSecretKey3245674")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")

# Apps Script & Email Integrations
CALENDAR_APPS_SCRIPT_URL = os.getenv("CALENDAR_APPS_SCRIPT_URL", "").strip()
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")

SETTINGS_ADMIN_TOKEN = os.getenv("SETTINGS_ADMIN_TOKEN", "")
SETTING_DEFAULTS = {
    "CALENDAR_APPS_SCRIPT_URL": CALENDAR_APPS_SCRIPT_URL,
    "TOLERANCE_24_HOURS_MINUTES": os.getenv("TOLERANCE_24_HOURS_MINUTES", "5"),
    "TOLERANCE_4_HOURS_MINUTES": os.getenv("TOLERANCE_4_HOURS_MINUTES", "5"),
    "TOLERANCE_10_MINS_MINUTES": os.getenv("TOLERANCE_10_MINS_MINUTES", "5"),
}
SETTING_LABELS = {
    "CALENDAR_APPS_SCRIPT_URL": "Google Apps Script Engine Web App URL",
    "TOLERANCE_24_HOURS_MINUTES": "24-hour Reminder Window (+/- minutes)",
    "TOLERANCE_4_HOURS_MINUTES": "4-hour Reminder Window (+/- minutes)",
    "TOLERANCE_10_MINS_MINUTES": "10-minute Reminder Window (+/- minutes)",
}

ai_client = OpenAI(api_key=OPENAI_API_KEY)

def get_setting(key, default=""):
    return db.get_setting(key, default)

def validate_setting_value(key, value):
    value = str(value or "").strip()
    if key not in SETTING_DEFAULTS:
        return False, "Unknown setting key."
    if key == "CALENDAR_APPS_SCRIPT_URL":
        if not value.startswith(("https://", "http://")):
            return False, "Apps Script URL must start with http:// or https://"
        return True, ""
    try:
        minutes = int(value)
    except ValueError:
        return False, "Window must be a whole number."
    if minutes < 1 or minutes > 120:
        return False, "Window must be between 1 and 120 minutes."
    return True, ""

def require_admin_token():
    if not SETTINGS_ADMIN_TOKEN:
        return True
    supplied = request.form.get("admin_token", "") or request.args.get("admin_token", "")
    return supplied == SETTINGS_ADMIN_TOKEN


def _availability_signal(user_query):
    """Return (is_confirming, is_declining) for class availability replies."""
    q = str(user_query or "").lower().strip()
    if not q:
        return (False, False)

    confirm_markers = ["confirm", "available", "attend", "be there", "will be there", "yes", "ok", "okay", "sure", "present"]
    decline_markers = ["sick", "unavailable", "can't make", "cannot make", "not available", "absent", "cancel", "unwell", "hospital", "ill", "won't attend"]

    has_confirm_word = any(word in q for word in confirm_markers)
    has_decline_word = any(word in q for word in decline_markers)
    if not (has_confirm_word or has_decline_word):
        return (False, False)

    class_context_markers = ["class", "lecture", "lesson", "session", "reminder", "today", "tomorrow", "11am", "12pm", "1pm", "2pm"]
    has_class_context = any(marker in q for marker in class_context_markers)
    is_short_direct_reply = len(q.split()) <= 6

    if not (has_class_context or is_short_direct_reply):
        return (False, False)

    is_confirming = has_confirm_word and not has_decline_word
    is_declining = has_decline_word
    return (is_confirming, is_declining)

# ==========================================
# 🗄️ STATE MANAGEMENT (MongoDB Wrapper)
# ==========================================
def init_db():
    try:
        for setting_key, setting_value in SETTING_DEFAULTS.items():
            existing = db.get_setting(setting_key)
            if not existing:
                db.set_setting(setting_key, str(setting_value), "system_default")
        print("✅ MongoDB state initialized.", flush=True)
    except Exception as e:
        print(f"❌ DB Init Error: {e}", flush=True)

def get_mapped_phone_for_alias(alias_id): return db.get_mapped_phone_for_alias(alias_id)
def upsert_contact_alias(alias_id, phone, name=""): db.upsert_contact_alias(alias_id, phone, name)
def remember_successful_delivery_route(identity, chat_id): db.remember_successful_delivery_route(identity, chat_id)
def get_preferred_delivery_route(identity): return db.get_preferred_delivery_route(identity)
def log_interaction(phone, query, response): db.log_interaction(phone, query, response)
def has_user_consented(phone): return db.has_user_consented(phone)
def mark_user_consented(phone): db.mark_user_consented(phone)
def save_chat_turn(phone, role, content): db.save_chat_turn(phone, role, content)
def get_recent_history(phone): return db.get_recent_history(phone)

init_db()

# ==========================================
# 🛠️ UTILITY CLEANING & NORMALIZATION 
# ==========================================

def resolve_lid_to_number(sender_id):
    # If it's already a normal number, just return it
    if not sender_id.endswith("@lid"):
        return sender_id

    # The @ symbol must be URL-encoded as %40 for this specific endpoint
    safe_lid = sender_id.replace("@", "%40")

    print(f"🔍 Attempting to resolve LID via WAHA LIDs API: {sender_id}")

    # Dynamic URL from environment variable (Render production)
    waha_base_url = os.getenv("WAHA_URL", "https://miva-waha.onrender.com").rstrip('/')
    url = f"{waha_base_url}/api/default/lids/{safe_lid}"

    # --- OLD LOCAL CODE (Uncomment to revert back for local testing) ---
    # url = f"http://127.0.0.1:3001/api/default/lids/{safe_lid}"

    try:
        response = requests.get(url, headers={"X-Api-Key": WAHA_API_KEY}, timeout=5)

        if response.status_code == 200:
            data = response.json()
            print("LID API RESPONSE:", data)

            # Extract the actual phone number ("pn") if WAHA found it
            phone_number = data.get("pn")
            if phone_number:
                print(f"✅ Successfully resolved to: {phone_number}")
                return phone_number
        else:
            print(f"Failed to fetch LID mapping. Status: {response.status_code}")

    except Exception as e:
        print(f"Error connecting to WAHA LIDs API: {e}")

    # Fallback to returning the LID if resolution fails
    return sender_id

def normalize_phone_for_db(phone_str):
    if not phone_str:
        return ""
    clean_str = str(phone_str).split('@')[0]
    cleaned = "".join(filter(str.isdigit, clean_str))
    if cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = "234" + cleaned[1:]
    return cleaned

def extract_message_payload(body):
    if not isinstance(body, dict):
        return {}
    for candidate_key in ("payload", "data", "message", "eventData"):
        candidate = body.get(candidate_key)
        if isinstance(candidate, dict) and any(candidate.get(key) for key in ("from", "chatId", "body", "text", "conversation", "caption")):
            return candidate
        if isinstance(candidate, dict):
            nested = candidate.get("message")
            if isinstance(nested, dict) and any(nested.get(key) for key in ("from", "chatId", "body", "text", "conversation", "caption")):
                return nested
    if any(body.get(key) for key in ("from", "chatId", "body", "text", "conversation", "caption")):
        return body
    return {}

def extract_sender_chat_id(payload):
    if not isinstance(payload, dict):
        return ""
    candidates = []
    for key in ("from", "chatId", "author", "participant"):
        value = payload.get(key)
        if value:
            candidates.append(str(value).strip())
    for suffix in ("@c.us", "@s.whatsapp.net", "@lid"):
        for candidate in candidates:
            if candidate.lower().endswith(suffix):
                return candidate
    for candidate in candidates:
        if candidate:
            return candidate
    return ""

def extract_message_text(payload):
    if not isinstance(payload, dict):
        return ""
    text = payload.get("body") or payload.get("text") or payload.get("conversation") or payload.get("caption") or ""
    if not text and isinstance(payload.get("message"), dict):
        nested = payload.get("message", {})
        text = nested.get("body") or nested.get("text") or nested.get("conversation") or nested.get("caption") or ""
    return str(text).strip()

def is_truthy_flag(value):
    if isinstance(value, bool): return value
    if isinstance(value, (int, float)): return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}
    return bool(value)

def extract_profile_name(payload):
    if not isinstance(payload, dict):
        return "Lecturer"
    nested_notify_name = payload.get("_data", {}).get("notifyName") if isinstance(payload.get("_data"), dict) else None
    name = payload.get("notifyName") or payload.get("pushName") or payload.get("name") or nested_notify_name
    if not name and isinstance(payload.get("sender"), dict):
        sender = payload.get("sender", {})
        name = sender.get("pushName") or sender.get("name") or sender.get("shortName")
    return str(name).strip() if name else "Lecturer"

# ==========================================
# 📊 DATA RETRIEVAL VIA APPS SCRIPT ENGINE
# ==========================================
def fetch_master_schedule(sender_phone=None, sender_name=None, query_text=None, allow_query_fallback=True):
    """POSTs to Apps Script, returns (schedule, profile, faqs, error_flag)."""
    apps_script_url = get_setting("CALENDAR_APPS_SCRIPT_URL", CALENDAR_APPS_SCRIPT_URL).strip()
    if not apps_script_url:
        print("⚠️ CALENDAR_APPS_SCRIPT_URL not configured.", flush=True)
        return [], {}, [], None

    payload = {
        "sender_phone": sender_phone or "",
        "sender_name": sender_name or "",
        "query_text": query_text or "",
    }

    for attempt in range(2):
        try:
            print(f"🔄 POSTing to Apps Script for {sender_phone} | {sender_name}...", flush=True)
            resp = requests.post(apps_script_url, json=payload, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                profile = data.get("profile") or {}
                schedule = data.get("schedule") or []
                faqs = data.get("faqs") or []

                if profile:
                    profile["course_code"] = profile.get("course_code") or profile.get("course code") or ""
                    profile["live_lesson_link"] = profile.get("live_lesson_link") or profile.get("live lesson link") or ""
                    profile["operations_manager"] = profile.get("operations_manager") or profile.get("operations manager") or "Operations Manager"
                    profile["operations_manager_email"] = profile.get("operations_manager_email") or profile.get("operations manager email") or "N/A"
                    if not profile.get("all_course_codes"):
                        profile["all_course_codes"] = [profile["course_code"]] if profile["course_code"] else []

                    print(f"🎯 Apps Script matched profile: {profile.get('name')} | Course: {profile.get('course_code')}", flush=True)
                    return schedule, profile, faqs, None

                # Valid response but no profile found
                return schedule, None, faqs, None

        except requests.exceptions.Timeout:
            print(f"⚠️ Apps Script timeout on attempt {attempt + 1}", flush=True)
        except Exception as e:
            print(f"⚠️ Apps Script connection error: {e}", flush=True)

    return [], None, [], "TIMEOUT_ERROR"


def fetch_monthly_lessons(sender_phone):
    """Fetches all monthly events for this lecturer directly from Apps Script."""
    apps_script_url = get_setting("CALENDAR_APPS_SCRIPT_URL", CALENDAR_APPS_SCRIPT_URL).strip()
    if not apps_script_url:
        return []

    try:
        clean_phone = normalize_phone_for_db(sender_phone)
        params = {
            "action": "monthly",
            "phone": clean_phone or sender_phone or ""
        }
        print(f"🔄 Requesting monthly schedule from Apps Script for {clean_phone}...", flush=True)
        resp = requests.get(apps_script_url, params=params, allow_redirects=True, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("events") or []
    except Exception as e:
        print(f"⚠️ Apps Script monthly lookup error: {e}", flush=True)

    return []

def format_monthly_lessons_response(events):
    if not events:
        return "You currently have no live lessons scheduled for this month."

    wat_tz = pytz.timezone("Africa/Lagos")
    current_month = datetime.datetime.now(wat_tz).strftime("%B %Y")
    lines = [f"📚 Your Live Lessons for {current_month}", ""]

    for idx, event in enumerate(events, start=1):
        course = event.get('course_code', 'Unknown')
        day = event.get('lecture_day', '')
        time_str = event.get('lecture_time', '')
        end_time = event.get('lecture_end_time', '')
        time_range = f"🕘 {time_str} – {end_time}" if end_time else f"🕘 {time_str}"

        lines.append(f"{idx}. {day}")
        lines.append(f"   {time_range}")
        lines.append(f"   Course: {course}")
        lines.append("")

    lines.append(f"Total lessons this month: {len(events)}")
    return "\n".join(lines)

def _is_live_lessons_query(user_query):
    q = str(user_query or "").lower().strip()
    if not q:
        return False
    live_lesson_markers = [
        "live lesson", "live lessons", "my lesson", "my lessons",
        "teaching schedule", "class schedule", "lecture schedule", "my schedule",
        "when am i teaching", "when am i lecturing", "am i teaching",
        "lessons this month", "classes this month", "teaching this month",
        "my classes", "my lectures", "my teaching", "do i have any class",
    ]
    if any(marker in q for marker in live_lesson_markers):
        return True
    return "this month" in q and any(w in q for w in ["lesson", "class", "teach", "lecture", "schedule"])

# ==========================================
# 💬 WAHA OUTBOUND & EMAIL ALERTS
# ==========================================
def send_whatsapp_text(to_phone, message_text):
    url = f"{WAHA_URL}/api/sendText"
    headers = {
        "X-Api-Key": WAHA_API_KEY,
        "Content-Type": "application/json"
    }

    raw_target = str(to_phone or "").strip()
    targets = []
    clean_number = normalize_phone_for_db(raw_target)
    preferred_route = get_preferred_delivery_route(raw_target)

    if preferred_route:
        targets.append(preferred_route)
    if clean_number:
        targets.append(f"{clean_number}@c.us")
    targets.append(raw_target)

    deduped_targets = []
    for t in targets:
        if t and t not in deduped_targets:
            deduped_targets.append(t)

    for chat_id in deduped_targets:
        payload = {
            "session": WAHA_SESSION,
            "chatId": chat_id,
            "text": message_text,
            "linkPreview": False
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=25)
            if res.status_code in [200, 201]:
                remember_successful_delivery_route(raw_target, chat_id)
                return True
        except Exception as e:
            print(f"❌ WAHA Dispatch Error: {e}", flush=True)

    return False

def send_operational_alert(manager_email, lecturer_name, raw_message):
    """Dispatches immediate notification email via Brevo API v3."""
    if not BREVO_API_KEY or not manager_email:
        print("⚠️ Skipping email alert: missing BREVO_API_KEY or manager email.", flush=True)
        return

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "sender": {"email": "noreply@miva.university", "name": "MIVA Academic Ops"},
        "to": [{"email": manager_email}],
        "subject": f"🚨 ATTENTION: Class Cancellation from {lecturer_name}",
        "textContent": (
            f"Hello Operations Manager,\n\n"
            f"Automated alert: Faculty member indicated unavailability.\n\n"
            f"Faculty Member: {lecturer_name}\n"
            f'Response: "{raw_message}"\n\n'
            f"Regards,\nAcademic Operations Automation Bot"
        ),
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in [200, 201, 202]:
            print(f"🚀 Operational alert sent to {manager_email}", flush=True)
    except Exception as e:
        print(f"❌ Brevo Transmission Error: {e}", flush=True)

def auto_escalate_expiry_watcher(tutor_phone_norm, message_text):
    wait_time = 180 if "5 min" in message_text.lower() else 900
    time.sleep(wait_time)
    try:
        doc = db.escalate_non_response(tutor_phone_norm)
        if doc:
            _, tutor_profile, _, _ = fetch_master_schedule(sender_phone=tutor_phone_norm)
            ops_manager = tutor_profile.get('operations_manager', 'Operations Manager')
            ops_manager_email = tutor_profile.get('operations_manager_email', 'Operations Manager Email' )
            tutor_name = tutor_profile.get('name', 'Lecturer')
            course_code = tutor_profile.get('course_code', 'assigned session')
            msg = f"⚠️ *NO RESPONSE ESCALATION*:\nLecturer *{tutor_name}* has NOT confirmed availability for *{course_code}*.\nOps Manager: *{ops_manager}*"
            send_whatsapp_text(tutor_phone_norm, msg)
    except Exception as err:
        print(f"❌ Non-response watcher error: {err}", flush=True)

# ==========================================
# 📚 MONTHLY LIVE LESSON REPORT HANDLERS
# ==========================================

def fetch_monthly_lessons(sender_phone):
    """Fetches all monthly events for this user directly from Apps Script."""
    apps_script_url = get_setting("CALENDAR_APPS_SCRIPT_URL", CALENDAR_APPS_SCRIPT_URL).strip()
    if not apps_script_url:
        print("⚠️ CALENDAR_APPS_SCRIPT_URL not configured.", flush=True)
        return []

    try:
        clean_phone = normalize_phone_for_db(sender_phone)
        params = {
            "action": "monthly",
            "phone": clean_phone or sender_phone or ""
        }
        print(f"🔄 Requesting monthly schedule from Apps Script for {clean_phone}...", flush=True)
        resp = requests.get(apps_script_url, params=params, allow_redirects=True, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            # Checks all possible JSON key variations returned by Apps Script
            return (
                data.get("events") or 
                data.get("monthly_events") or 
                data.get("calendar_events") or 
                []
            )
    except Exception as e:
        print(f"⚠️ Apps Script monthly lookup error: {e}", flush=True)

    return []


def format_monthly_lessons_response(events):
    """Formats calendar event objects into a clean, scannable WhatsApp report."""
    if not events:
        return "You currently have no live lessons scheduled for this month."

    wat_tz = pytz.timezone("Africa/Lagos")
    current_month = datetime.datetime.now(wat_tz).strftime("%B %Y")
    lines = [f"📚 *Your Live Lessons for {current_month}*", ""]

    for idx, event in enumerate(events, start=1):
        course = event.get('course_code') or event.get('course_code_calendar') or 'Unknown Course'
        day = event.get('lecture_day', '')
        time_str = event.get('lecture_time', '')
        end_time = event.get('lecture_end_time', '')
        room_link = event.get('room_link', '')

        time_range = f"🕘 {time_str} – {end_time}" if end_time else f"🕘 {time_str}"

        lines.append(f"*{idx}. {day}*")
        lines.append(f"   {time_range}")
        lines.append(f"   Course: {course}")
        if room_link and room_link != "No Link Provided":
            lines.append(f"   🔗 Link: {room_link}")
        lines.append("")

    lines.append(f"Total lessons this month: *{len(events)}*")
    return "\n".join(lines)


def _is_live_lessons_query(user_query):
    """Detects if the incoming user query is asking for a monthly live lesson report."""
    q = str(user_query or "").lower().strip()
    if not q:
        return False

    # Direct phrase triggers
    live_lesson_markers = [
        "live lesson report", "monthly report", "lesson report",
        "live lesson", "live lessons", "my lesson", "my lessons",
        "teaching schedule", "class schedule", "lecture schedule", "my schedule",
        "when am i teaching", "when am i lecturing", "am i teaching",
        "lessons this month", "classes this month", "teaching this month",
        "my classes", "my lectures", "my teaching", "do i have any class",
    ]
    
    if any(marker in q for marker in live_lesson_markers):
        return True
        
    # Catch combinations with "month" / "monthly"
    return ("month" in q or "monthly" in q) and any(w in q for w in ["lesson", "class", "teach", "lecture", "schedule", "report"])

def _is_greeting_only(user_query):
    """Detects if a message is strictly a greeting and contains no actionable intent."""
    q = str(user_query or "").lower().strip()
    q_clean = "".join(c for c in q if c.isalnum() or c.isspace())
    words = q_clean.split()

    if not words or len(words) > 4:
        return False

    # Never treat messages containing intent/emergency keywords as simple greetings
    intent_signals = [
        "sick", "unavailable", "confirm", "cannot", "cant", "unable", 
        "cancel", "miss", "class", "schedule", "link", "code", "email", 
        "manager", "grade", "pay", "salary", "help", "issue", "problem"
    ]
    if any(signal in q_clean for signal in intent_signals):
        return False

    common_greetings = {
        "hello", "hi", "hey", "heya", "good morning", "good afternoon", 
        "good evening", "howdy", "whats up", "whatsup", "hy", "greetings"
    }
    fillers = {"there", "bot", "assistant", "miva", "sir", "ma", "everyone"}

    if q_clean in common_greetings:
        return True

    return all(w in common_greetings or w in fillers for w in words)

## ==========================================
# ⚡ CORE WHATSAPP INBOUND WORKER
# ==========================================
def background_processor(body):
    try:
        payload = extract_message_payload(body)
        if not payload:
            return

        from_me = is_truthy_flag(payload.get("fromMe") or payload.get("_data", {}).get("fromMe"))
        if from_me:
            return

        tutor_phone_raw = extract_sender_chat_id(payload)
        tutor_phone_raw_before_resolve = tutor_phone_raw
        tutor_phone_raw = resolve_lid_to_number(tutor_phone_raw)
        if not tutor_phone_raw or "@g.us" in tutor_phone_raw or tutor_phone_raw == "status@broadcast":
            return

        tutor_phone_norm = normalize_phone_for_db(tutor_phone_raw)
        
        has_media = is_truthy_flag(payload.get("hasMedia") or payload.get("_data", {}).get("hasMedia"))
        if has_media:
            send_whatsapp_text(tutor_phone_raw, "I can only process text messages.")
            return

        user_query = extract_message_text(payload)
        if not user_query:
            return

        print(f"📥 Processing message from {tutor_phone_norm}: '{user_query}'", flush=True)
        whatsapp_profile_name = extract_profile_name(payload)

        # ----------------------------------------------------
        # 🔄 FETCH PROFILE, SCHEDULE & FAQS VIA APPS SCRIPT
        # ----------------------------------------------------
        current_schedule, tutor_profile, faqs, fetch_err = fetch_master_schedule(
            sender_phone=tutor_phone_raw,
            sender_name=whatsapp_profile_name,
            query_text=user_query,
        )

        # Handle Network / Timeout Failures
        if fetch_err == "TIMEOUT_ERROR":
            print(f"⏳ Google Apps Script timed out for {tutor_phone_raw}", flush=True)
            send_whatsapp_text(
                tutor_phone_raw, 
                "We are experiencing a temporary network delay reaching the portal. Please try sending your message again in a few seconds."
            )
            return

        # Handle Unregistered Lecturers
        if not tutor_profile:
            print(f"🔒 Access blocked for {tutor_phone_raw}: not found on master record.", flush=True)
            send_whatsapp_text(
                tutor_phone_raw, 
                "Your phone number is not registered on the Miva Master Lecturer Record. Please contact your Operations Manager for access."
            )
            return

        # Normalize Profile Fields
        tutor_name = tutor_profile.get("name") or whatsapp_profile_name
        sheet_course_code = tutor_profile.get("course_code") or ""
        ops_manager_name = tutor_profile.get("operations_manager") or "Operations Manager"
        ops_manager_email = tutor_profile.get("operations_manager_email") or ""
        live_lesson_link = tutor_profile.get("live_lesson_link") or ""

        # Consent Lifecycle Check
        old_lid_norm = normalize_phone_for_db(tutor_phone_raw_before_resolve)
        if not has_user_consented(tutor_phone_norm) and has_user_consented(old_lid_norm):
            mark_user_consented(tutor_phone_norm)
            print(f"✅ Migrated consent from {old_lid_norm} to {tutor_phone_norm}", flush=True)
        elif not has_user_consented(tutor_phone_norm):
            print(f"🤝 Auto-consenting verified lecturer {tutor_phone_norm}", flush=True)
            mark_user_consented(tutor_phone_norm)

        try:
            db.mark_reminder_response(tutor_phone_norm)
        except Exception:
            pass

        normalized_query = user_query.lower().strip()

        # ----------------------------------------------------
        # 🚨 1. AVAILABILITY SIGNAL INTERCEPT (CONFIRM / DECLINE / SICK)
        # ----------------------------------------------------
        is_confirming, is_declining = _availability_signal(user_query)
        if is_confirming or is_declining:
            doc = db.get_latest_sent_reminder(tutor_phone_norm)
            
            if is_confirming:
                if doc:
                    db.confirm_reminder(doc["_id"], tutor_phone_norm)
                
                confirm_reply = f"Thank you {tutor_name}! Your attendance for your upcoming class has been confirmed."
                save_chat_turn(tutor_phone_norm, "assistant", confirm_reply)
                send_whatsapp_text(tutor_phone_raw, confirm_reply)
                log_interaction(tutor_phone_norm, user_query, confirm_reply)
                return

            elif is_declining:
                if doc:
                    db.escalate_reminder(doc["_id"], tutor_phone_norm)
                
                send_operational_alert(ops_manager_email, tutor_name, sheet_course_code, f"Unavailable/Sick: {user_query}")
                
                decline_reply = (
                    f"Thank you for letting us know, {tutor_name}.\n\n"
                    f"We have logged your unavailability and notified your Operations Manager (*{ops_manager_name}*) "
                    f"to arrange coverage for your class."
                )
                save_chat_turn(tutor_phone_norm, "assistant", decline_reply)
                send_whatsapp_text(tutor_phone_raw, decline_reply)
                log_interaction(tutor_phone_norm, user_query, decline_reply)
                return

        # ----------------------------------------------------
        # 🔒 2. SECURITY & POLICY RISK FILTER (Restricted Topics)
        # ----------------------------------------------------
        sensitive_keywords = ["grade", "result", "score", "salary", "payroll", "pay", "stipend", "compensation"]
        if any(keyword in normalized_query for keyword in sensitive_keywords):
            email_info = f" ({ops_manager_email})" if ops_manager_email else ""
            escalation_text = (
                f"I am restricted from processing requests regarding grades, results, salary, or payroll.\n\n"
                f"Please contact your Operations Manager, *{ops_manager_name}*{email_info}, for assistance."
            )
            save_chat_turn(tutor_phone_norm, "assistant", escalation_text)
            send_whatsapp_text(tutor_phone_raw, escalation_text)
            log_interaction(tutor_phone_norm, user_query, escalation_text)
            return

        # ----------------------------------------------------
        # ⚡ 3. GREETING FAST INTERCEPT
        # ----------------------------------------------------
        if _is_greeting_only(normalized_query):
            greeting_reply = f"Hello {tutor_name}! 👋 How can I assist you with your live lessons or schedule today?"
            save_chat_turn(tutor_phone_norm, "assistant", greeting_reply)
            send_whatsapp_text(tutor_phone_raw, greeting_reply)
            log_interaction(tutor_phone_norm, user_query, greeting_reply)
            return

        # ----------------------------------------------------
        # ⚡ 4. SPECIFIC FIELD INTERCEPTS
        # ----------------------------------------------------
        if any(k in normalized_query for k in ["course code", "my code"]):
            reply = f"Your assigned course code is {sheet_course_code}." if sheet_course_code else "No course code is currently assigned to your record."
            save_chat_turn(tutor_phone_norm, "assistant", reply)
            send_whatsapp_text(tutor_phone_raw, reply)
            log_interaction(tutor_phone_norm, user_query, reply)
            return

        if any(k in normalized_query for k in ["ops manager", "operations manager", "my manager"]):
            reply = f"Your Operations Manager is {ops_manager_name}."
            if ops_manager_email:
                reply += f" You can reach them via email at: {ops_manager_email}"
            save_chat_turn(tutor_phone_norm, "assistant", reply)
            send_whatsapp_text(tutor_phone_raw, reply)
            log_interaction(tutor_phone_norm, user_query, reply)
            return

        if any(k in normalized_query for k in ["meeting link", "lesson link", "zoom link", "class link", "room link"]):
            reply = f"Your live lesson link is: {live_lesson_link}" if live_lesson_link else "No live lesson link is currently configured on your record. Please contact your Operations Manager."
            save_chat_turn(tutor_phone_norm, "assistant", reply)
            send_whatsapp_text(tutor_phone_raw, reply)
            log_interaction(tutor_phone_norm, user_query, reply)
            return

        matched_email = tutor_profile.get('email', '')
        if any(k in normalized_query for k in ["email", "my email", "email address"]):
            email_reply = f"Your registered email address is: {matched_email}" if matched_email else "No email address found on your record."
            save_chat_turn(tutor_phone_norm, "assistant", email_reply)
            send_whatsapp_text(tutor_phone_raw, email_reply)
            log_interaction(tutor_phone_norm, user_query, email_reply)
            return

        # If they ask for their full monthly schedule
        if _is_live_lessons_query(user_query):
            monthly_events = fetch_monthly_lessons(tutor_phone_norm)
            monthly_reply = format_monthly_lessons_response(monthly_events)
            save_chat_turn(tutor_phone_norm, "assistant", monthly_reply)
            send_whatsapp_text(tutor_phone_raw, monthly_reply)
            log_interaction(tutor_phone_norm, user_query, monthly_reply)
            return

        # ----------------------------------------------------
        # 🧠 5. OPENAI GENERATOR (INCLUDES LIVE SHEET FAQS)
        # ----------------------------------------------------
        # Prepare the FAQ text
        formatted_faqs = ""
        if faqs:
            for item in faqs:
                formatted_faqs += f"Q: {item['q']}\nA: {item['a']}\n\n"
        else:
            formatted_faqs = "No additional FAQ entries provided."

        # Prepare the Daily Schedule text
        formatted_schedule_text = ""
        if current_schedule:
            for row in current_schedule:
                formatted_schedule_text += f"- Course: {row.get('course_code_calendar')}, Day/Time: {row.get('lecture_day')} at {row.get('lecture_time')}, Room: {row.get('room_link')}\n"
        else:
            formatted_schedule_text = "No live sessions scheduled for today."

        wat_tz = pytz.timezone("Africa/Lagos")
        current_time_wat = datetime.datetime.now(wat_tz).strftime("%A, %B %d, %Y at %I:%M %p")

        # Inject everything into OpenAI's system prompt
        system_prompt = f"""
You are the Lecturer Support Assistant for Miva Open University.
Personality: Highly intelligent, efficient, polite human coordinator.

STRICT RULES:
1. Max 2 short sentences. Get straight to the point.
2. DO NOT state or report whether the lecturer has a class today UNLESS they explicitly asked about their schedule, classes, or teaching status.
3. If the user's query matches a question in the FAQ KNOWLEDGE BASE below, answer strictly using that information.
4. If the user is engaging in general conversation or greeting, respond naturally and politely.
5. No bold asterisks (*) or markdown formatting.

FAQ KNOWLEDGE BASE:
{formatted_faqs}

CONTEXT:
- System Time: {current_time_wat}
- Lecturer Name: {tutor_name}
- Manager Contact: {ops_manager_name} ({ops_manager_email})
- Assigned Course Code: {sheet_course_code}
- Live Lesson Link: {live_lesson_link or 'Check Portal'}
- SCHEDULE DATA:
{formatted_schedule_text}
"""
        save_chat_turn(tutor_phone_norm, "user", user_query)
        conversation_history = get_recent_history(tutor_phone_norm)

        messages_payload = [{"role": "system", "content": system_prompt}] + conversation_history

        ai_response = ai_client.chat.completions.create(
            model=FAQ_REPLY_MODEL,
            messages=messages_payload,
            temperature=0.4
        )

        final_reply = str(ai_response.choices[0].message.content or "").strip()
        
        save_chat_turn(tutor_phone_norm, "assistant", final_reply)
        send_whatsapp_text(tutor_phone_raw, final_reply)
        log_interaction(tutor_phone_norm, user_query, final_reply)

    except Exception as background_err:
        print(f"💥 Background Worker Fault: {background_err}", flush=True)
# ==========================================
# 🚀 API ENDPOINTS & SETTINGS
# ==========================================
@app.route('/send_internal_reminder', methods=['POST'])
def send_internal_reminder():
    data = request.get_json() or {}
    to_phone = data.get("to")
    message_text = data.get("message")
    
    success = send_whatsapp_text(to_phone, message_text)
    if success:
        try:
            tutor_phone_norm = normalize_phone_for_db(to_phone)
            msg = str(message_text or "").lower()
            tier = "24_HOURS" if "24 hour" in msg or "24-hour" in msg else ("10_MINS" if "10 min" in msg else "4_HOURS")
            db.insert_sent_reminder(tutor_phone_norm, tier)
            threading.Thread(target=auto_escalate_expiry_watcher, args=(tutor_phone_norm, message_text)).start()
        except Exception as e:
            print(f"❌ Reminder DB Error: {e}", flush=True)
        return jsonify({"status": "success"}), 200
    
    return jsonify({"status": "failed", "error": "WAHA dispatch failed"}), 400

@app.route('/webhook', methods=['POST'])
def handle_incoming_messages():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"status": "no_json"}), 200

    # ⚡ Spawn background processing instantly, return 200 immediately
    threading.Thread(target=background_processor, args=(body,), daemon=True).start()

    return jsonify({"status": "acknowledged"}), 200

@app.route('/settings', methods=['GET'])
def settings_page():
    init_db()
    settings_rows = db.get_all_settings()
    pending_rows = db.get_pending_changes()
    html = """
    <!DOCTYPE html><html><head><title>MIVA Settings</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-slate-100 p-6"><main class="max-w-4xl mx-auto space-y-6">
    <h1 class="text-2xl font-bold">MIVA Engine Settings</h1>
    <div class="bg-white p-6 rounded-xl shadow border">
    <h2 class="font-bold mb-4">Active Settings</h2>
    <ul>{% for r in settings_rows %}<li><strong>{{ labels.get(r.key, r.key) }}:</strong> {{ r.value }}</li>{% endfor %}</ul>
    </div></main></body></html>
    """
    return render_template_string(html, labels=SETTING_LABELS, settings_rows=settings_rows, pending_rows=pending_rows)

@app.route('/settings/request', methods=['POST'])
def settings_request_change():
    key = request.form.get("key", "").strip()
    proposed_value = request.form.get("proposed_value", "").strip()
    valid, error = validate_setting_value(key, proposed_value)
    if not valid:
        return redirect(url_for('settings_page', message=error))
    db.add_pending_change(key, proposed_value, "admin", "Updated setting")
    return redirect(url_for('settings_page', message='Change submitted.'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)