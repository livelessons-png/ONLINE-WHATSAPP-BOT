import os
import time
import threading
import logging
import requests
from dotenv import load_dotenv
import mongo_db as db

# ========================================================
# 1. INITIALIZATION & GLOBAL CONFIGURATIONS
# ========================================================
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [REMINDER DAEMON] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

APPS_SCRIPT_URL = os.getenv("CALENDAR_APPS_SCRIPT_URL", "").strip()
WAHA_URL = os.getenv("WAHA_URL", "http://localhost:3001")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")

POLL_INTERVAL_SECONDS = int(os.getenv("REMINDER_POLL_INTERVAL", "300"))

# ==========================================
# UTILITIES & WHATSAPP DISPATCH
# ==========================================
def normalize_phone_for_db(phone_str):
    if not phone_str:
        return ""
    clean_str = str(phone_str).split('@')[0]
    cleaned = "".join(filter(str.isdigit, clean_str))
    if cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = "234" + cleaned[1:]
    return cleaned

def send_whatsapp_text(to_phone, message_text):
    """Sends a message via WAHA API ONLY to known contacts or existing chats in the DB."""
    clean_number = normalize_phone_for_db(to_phone)
    if not clean_number:
        logger.warning("⚠️ No valid phone number provided.")
        return False

    url = f"{WAHA_URL}/api/sendText"
    headers = {
        "X-Api-Key": WAHA_API_KEY,
        "Content-Type": "application/json"
    }
    
    target = f"{clean_number}@c.us"

    payload = {
        "session": WAHA_SESSION,
        "chatId": target,
        "text": message_text,
        "linkPreview": False
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if res.status_code in [200, 201]:
            logger.info(f"✅ WAHA message dispatched to {clean_number}")
            return True
        elif res.status_code in [400, 404]:
            # WAHA drops it because they haven't engaged or aren't a saved contact in your DB
            logger.warning(f"🚫 Skipped {clean_number}: Unengaged/Cold number rejected by WAHA.")
            return False
        else:
            logger.warning(f"⚠️ WAHA dispatch failed with status {res.status_code}: {res.text}")
            
    except Exception as e:
        logger.error(f"❌ WAHA Connection Error: {e}")
        
    return False

# ==========================================
# ESCALATION WATCHER
# ==========================================
def send_operational_alert(manager_email, lecturer_name, course_code, issue_type):
    """Emails the Operations Manager via Brevo if a lecturer fails to respond."""
    if not BREVO_API_KEY or not manager_email:
        logger.warning(f"⚠️ Missing Brevo API Key or Manager Email. Skipping email alert for {lecturer_name}.")
        return

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "sender": {"email": "noreply@miva.university", "name": "MIVA Academic Ops"},
        "to": [{"email": manager_email}],
        "subject": f"🚨 ESCALATION: Non-Response from {lecturer_name}",
        "textContent": (
            f"Hello,\n\n"
            f"Automated Alert: A faculty member has not confirmed their upcoming class.\n\n"
            f"Faculty Member: {lecturer_name}\n"
            f"Course Code: {course_code}\n"
            f"Issue: {issue_type}\n\n"
            f"Please reach out to them immediately to ensure class coverage.\n\n"
            f"Regards,\nMiva Automation Engine"
        ),
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in [200, 201, 202]:
            logger.info(f"📧 Escalation email sent to {manager_email}")
    except Exception as e:
        logger.error(f"❌ Brevo Email Error: {e}")

def auto_escalate_expiry_watcher(tutor_phone_norm, tutor_name, course_code, ops_manager, ops_email, tier):
    """Waits 15 minutes and checks if attendance was confirmed in DB."""
    wait_time = 900  # 15 minutes
    logger.info(f"⏳ Started {wait_time}s escalation watcher for {tutor_name} ({tier})")
    time.sleep(wait_time)
    
    try:
        # DB method checks if the reminder was answered; escalates if pending
        doc = db.escalate_non_response(tutor_phone_norm)
        if doc:
            warning_msg = (
                f"🚨 *NO RESPONSE ESCALATION*:\n"
                f"We have not received your confirmation for *{course_code}*. "
                f"Your Operations Manager (*{ops_manager}*) has been notified to ensure class coverage."
            )
            send_whatsapp_text(tutor_phone_norm, warning_msg)
            send_operational_alert(ops_email, tutor_name, course_code, "Failed to confirm attendance within the 15-minute time limit.")
            logger.info(f"🚨 Escalated non-response for {tutor_name} to {ops_manager}")
        else:
            logger.info(f"✅ Watcher complete: {tutor_name} successfully confirmed attendance.")
    except Exception as err:
        logger.error(f"❌ Non-response watcher error: {err}")

# ==========================================
# CORE DAEMON LOOP
# ==========================================
def fetch_and_process_reminders():
    """Polls Google Apps Script for active reminders and dispatches them."""
    if not APPS_SCRIPT_URL:
        logger.error("❌ CALENDAR_APPS_SCRIPT_URL is not set. Daemon cannot run.")
        return

    logger.info("🔄 Polling Google Apps Script for active reminders...")
    
    try:
        resp = requests.get(APPS_SCRIPT_URL, params={"action": "reminders"}, timeout=60)
        
        if resp.status_code != 200:
            logger.warning(f"⚠️ Apps Script returned status {resp.status_code}")
            return
            
        data = resp.json()
        reminders = data.get("reminders", [])
        
        if not reminders:
            logger.info("ℹ️ No active reminders pending in this window.")
            return

        for r in reminders:
            raw_phone = r.get("phone", "")
            norm_phone = normalize_phone_for_db(raw_phone)
            name = r.get("name", "Lecturer")
            course_details = r.get("course_code", "Your Class")
            class_date = r.get("lecture_day", "Today/Tomorrow")
            class_time = r.get("lecture_time", "soon")
            meet_link = r.get("room_link", "Check Portal")
            tier = r.get("tier", "24_HOURS")
            ops_manager = r.get("ops_manager", "Operations Manager")
            ops_email = r.get("ops_email", "")
            event_id = r.get("id") or f"{norm_phone}_{course_details}_{class_date}_{tier}"

            if not norm_phone:
                continue

            # Pass event_id or composite key to make duplicate checks event-specific
            try:
                db.insert_sent_reminder(
                    phone=norm_phone, 
                    tier=tier, 
                    event_id=event_id, 
                    course_code=course_details
                ) 
            except Exception as e:
                if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                    logger.info(f"⏩ Skipping duplicate reminder for {norm_phone} ({course_details} - {tier})")
                    continue
                else:
                    logger.error(f"DB Insert Error: {e}")
                    continue

            # Dynamic Text based on Tier
            action_prompt = ""
            begins_in_text = ""
            
            if tier == "24_HOURS":
                begins_in_text = "is scheduled for tomorrow"
                action_prompt = "\n\n*Action Required:* Please reply *'Confirm'* to acknowledge, or *'Unavailable'* if you cannot make it."
            elif tier == "4_HOURS":
                begins_in_text = "begins in 4 hours"
                action_prompt = "\n\n*Action Required:* Please reply *'Confirm'* to acknowledge, or *'Unavailable'* if you cannot make it."
            else:
                begins_in_text = "begins in 10 minutes"
                action_prompt = ""

            message_text = (
                f"📚 *MIVA OPEN UNIVERSITY - LECTURE REMINDER* 📚\n\n"
                f"Hello {name},\n\n"
                f"This is a friendly notification that your Live Lesson {begins_in_text}:\n\n"
                f"*Course:* {course_details}\n"
                f"*Date:* {class_date}\n"
                f"*Time:* {class_time}\n"
                f"*Lesson Link:* {meet_link}\n\n"
                f"Please ensure you are logged into the session 10 minutes prior to start.{action_prompt}\n\n"
                f"Have an excellent session!"
            )

            success = send_whatsapp_text(norm_phone, message_text)
            
            # Spawn Escalation Watcher with daemon=True so it doesn't block shutdown
            if success and tier in ["24_HOURS", "4_HOURS"]:
                watcher_thread = threading.Thread(
                    target=auto_escalate_expiry_watcher, 
                    args=(norm_phone, name, course_details, ops_manager, ops_email, tier),
                    daemon=True
                )
                watcher_thread.start()

    except Exception as e:
        logger.error(f"💥 Daemon Loop Error: {e}")

def run():
    logger.info("🚀 MIVA Reminder Daemon Initialized and Running.")
    while True:
        fetch_and_process_reminders()
        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == '__main__':
    run()