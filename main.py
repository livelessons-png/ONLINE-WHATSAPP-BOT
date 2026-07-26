"""
Unified entrypoint for MIVA WhatsApp Bot.
Combines WAHA_INTERACT + DASHBOARD routes under one Flask app
and runs the Reminder Daemon in a background thread.
"""
import threading
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MAIN] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import modules to register their routes
import WAHA_INTERACT
import DASHBOARD

# Use WAHA_INTERACT's app as the single Flask application
# Copy all routes and before_request handlers from DASHBOARD into it
bot_app = WAHA_INTERACT.app
dash_app = DASHBOARD.app

for rule in dash_app.url_map.iter_rules():
    endpoint = rule.endpoint
    func = dash_app.view_functions.get(endpoint)
    if func and endpoint not in bot_app.view_functions:
        bot_app.add_url_rule(
            rule.rule,
            endpoint=endpoint,
            view_func=func,
            methods=list(rule.methods) if rule.methods else None,
        )

# Copy error handlers
for code, handler in dash_app.error_handler_spec.get(None, {}).items():
    if code not in bot_app.error_handler_spec.get(None, {}):
        bot_app.register_error_handler(code, handler)

# Copy all before/after request handlers from dashboard
bot_app.before_request_funcs.setdefault(None, [])
for handler in dash_app.before_request_funcs.get(None, []):
    if handler not in bot_app.before_request_funcs[None]:
        bot_app.before_request_funcs[None].append(handler)

app = bot_app

# Start Reminder Daemon in background
import WAHA_REMINDERV2 as reminder_daemon


def start_reminder_daemon():
    logger.info("🚀 Reminder Daemon loop started.")
    reminder_daemon.run()


if __name__ == '__main__':
    daemon_thread = threading.Thread(target=start_reminder_daemon, daemon=True)
    daemon_thread.start()
    logger.info("✅ Reminder Daemon thread launched.")

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🌐 Starting unified web server on 0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
