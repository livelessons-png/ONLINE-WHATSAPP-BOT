import os
import datetime
import requests
from flask import Flask, render_template_string, request, jsonify, Response
from dotenv import load_dotenv
import mongo_db as db

load_dotenv()

app = Flask(__name__)

# ========================================================
# 1. ENVIRONMENT CONFIGURATION & ALIGNMENT
# ========================================================
# Aligning WAHA URL with waha_reminder.py & Render environment
WAHA_PORT = os.getenv("WHATSAPP_API_PORT", "3001")
WAHA_URL = os.getenv("WAHA_URL", f"http://localhost:{WAHA_PORT}").rstrip("/")
WEBHOOK_URL = os.getenv("WHATSAPP_HOOK_URL", os.getenv("WEBHOOK_URL", "http://localhost:5000/webhook"))
WAHA_KEY = os.getenv("WAHA_API_KEY", "")


# ========================================================
# 2. NAVIGATION INDEX ROUTE
# ========================================================
@app.route("/")
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>MIVA Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <meta http-equiv="refresh" content="30">
    </head>
    <body class="bg-slate-100 p-6">
    <main class="max-w-4xl mx-auto space-y-6">
        <div class="bg-slate-900 text-white rounded-2xl p-6 shadow">
            <h1 class="text-3xl font-bold">MIVA Open University</h1>
            <p class="text-indigo-300 text-sm">Automation Engine & Analytics Hub</p>
        </div>
        <a href="/analytics" class="block bg-white rounded-xl p-6 shadow-sm border hover:bg-slate-50 text-lg font-bold text-center">Executive Insights Hub</a>
        <a href="/api/stats" class="block bg-white rounded-xl p-6 shadow-sm border hover:bg-slate-50 text-lg font-bold text-center">JSON Stats API</a>
        <a href="/qr" class="block bg-white rounded-xl p-6 shadow-sm border hover:bg-slate-50 text-lg font-bold text-center text-emerald-600">WhatsApp QR Code & Session</a>
    </main>
    </body>
    </html>
    """


# ========================================================
# 3. EXECUTIVE ANALYTICS HUB
# ========================================================
@app.route("/analytics", methods=["GET"])
def live_management_analytics():
    timeframe = request.args.get("timeframe", "all")
    match_filter = {}
    now = datetime.datetime.now()

    if timeframe == "today":
        start_date = now.strftime("%Y-%m-%d")
        match_filter["sent_at"] = {"$regex": f"^{start_date}"}
    elif timeframe == "yesterday":
        start_date = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        match_filter["sent_at"] = {"$regex": f"^{start_date}"}
    elif timeframe == "last_7_days":
        start_date = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        match_filter["sent_at"] = {"$gte": start_date}
    elif timeframe == "last_30_days":
        start_date = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        match_filter["sent_at"] = {"$gte": start_date}
    elif timeframe == "this_month":
        month_str = now.strftime("%Y-%m")
        match_filter["sent_at"] = {"$regex": f"^{month_str}"}

    metrics = {
        "sent": 0, "delivered": 0, "response_rate": 0.0,
        "questions": 0, "escalations": 0, "attendance_rate": 0.0, "ai_confidence": 0.0,
    }
    reminders = []
    global_tier_counts = {"24_HOURS": 0, "4_HOURS": 0, "10_MINS": 0}

    try:
        reminders = list(db.get_db().sent_reminders.find(
            match_filter, {"_id": 0, "event_uid": 1, "course_code": 1, "phone": 1, "tier": 1,
                           "sent_at": 1, "status": 1, "is_confirmed": 1, "ai_confidence": 1}
        ).sort("sent_at", -1).limit(50))

        tier_pipeline = [{"$match": match_filter}, {"$group": {"_id": "$tier", "qty": {"$sum": 1}}}]
        for t_row in list(db.get_db().sent_reminders.aggregate(tier_pipeline)):
            raw_tier = str(t_row["_id"]).upper() if t_row["_id"] else ""
            qty = t_row["qty"]
            if "24" in raw_tier:
                global_tier_counts["24_HOURS"] += qty
            elif "4" in raw_tier:
                global_tier_counts["4_HOURS"] += qty
            else:
                global_tier_counts["10_MINS"] += qty

        metrics_pipeline = [
            {"$match": match_filter},
            {"$group": {
                "_id": None,
                "sent": {"$sum": 1},
                "delivered": {"$sum": {"$cond": [{"$in": ["$status", ["delivered", "read"]]}, 1, 0]}},
                "responses": {"$sum": {"$cond": [{"$eq": ["$is_response", 1]}, 1, 0]}},
                "questions": {"$sum": {"$ifNull": ["$questions_count", 0]}},
                "escalations": {"$sum": {"$cond": [{"$eq": ["$is_escalated", 1]}, 1, 0]}},
                "confirmations": {"$sum": {"$cond": [{"$eq": ["$is_confirmed", 1]}, 1, 0]}},
                "avg_conf": {"$avg": {"$ifNull": ["$ai_confidence", 0]}},
            }}
        ]
        results = list(db.get_db().sent_reminders.aggregate(metrics_pipeline))
        if results:
            row = results[0]
            if row.get("sent", 0) > 0:
                metrics["sent"] = row["sent"]
                metrics["delivered"] = row.get("delivered", 0)
                metrics["questions"] = row.get("questions", 0)
                metrics["escalations"] = row.get("escalations", 0)
                metrics["ai_confidence"] = round((row.get("avg_conf", 0.0) or 0.0) * 100, 1)
                deliv = row.get("delivered", 0) or 0
                if deliv > 0:
                    metrics["response_rate"] = round(((row.get("responses", 0) or 0) / deliv) * 100, 1)
                    metrics["attendance_rate"] = round(((row.get("confirmations", 0) or 0) / deliv) * 100, 1)

    except Exception as e:
        return f"<h3 style='color:red; text-align:center; margin-top:50px;'>Database error: {e}</h3>", 500

    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>MIVA University | Executive Insights Hub</title>
        <meta http-equiv="refresh" content="30">
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Inter', sans-serif; background-color: #f8fafc; }
            .glass-card { background: #ffffff; border: 1px solid #e2e8f0; transition: all 0.2s ease; }
            .glass-card:hover { transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05); }
            .pulse-dot { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
            @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
            .table-container::-webkit-scrollbar { width: 6px; height: 6px; }
            .table-container::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
        </style>
    </head>
    <body class="text-slate-800 antialiased p-4 md:p-8">
        <div class="max-w-7xl mx-auto">
            <div class="bg-slate-900 rounded-2xl shadow-xl p-6 mb-8 flex flex-col md:flex-row justify-between items-center border-b-4 border-indigo-600">
                <div>
                    <h1 class="text-3xl font-bold text-white tracking-tight">MIVA Open University</h1>
                    <p class="text-indigo-400 mt-1 text-sm font-semibold uppercase tracking-widest">Automation Intelligence Dashboard</p>
                </div>
                <div class="mt-4 md:mt-0 flex flex-col md:flex-row items-center gap-4">
                    <form id="dateFilterForm" method="GET" action="/analytics" class="flex items-center gap-2">
                        <select name="timeframe" onchange="document.getElementById('dateFilterForm').submit()"
                                class="bg-slate-800 text-slate-200 border border-slate-700 rounded-lg px-4 py-2 text-sm font-medium focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-colors cursor-pointer outline-none">
                            <option value="all" {% if timeframe == 'all' %}selected{% endif %}>All Time</option>
                            <option value="today" {% if timeframe == 'today' %}selected{% endif %}>Today</option>
                            <option value="yesterday" {% if timeframe == 'yesterday' %}selected{% endif %}>Yesterday</option>
                            <option value="last_7_days" {% if timeframe == 'last_7_days' %}selected{% endif %}>Last 7 Days</option>
                            <option value="last_30_days" {% if timeframe == 'last_30_days' %}selected{% endif %}>Last 30 Days</option>
                            <option value="this_month" {% if timeframe == 'this_month' %}selected{% endif %}>This Month</option>
                        </select>
                    </form>
                    <div class="flex items-center gap-3 bg-emerald-500/10 px-4 py-2 rounded-full border border-emerald-500/20">
                        <div class="w-2.5 h-2.5 bg-emerald-400 rounded-full pulse-dot"></div>
                        <span class="text-emerald-400 text-xs font-bold tracking-wide">SYSTEM OPERATIONAL</span>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4 mb-8">
                <div class="glass-card rounded-xl p-4 shadow-sm border-l-4 border-l-slate-700">
                    <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Sent</p>
                    <p class="text-2xl font-bold text-slate-900">{{ m.sent }}</p>
                </div>
                <div class="glass-card rounded-xl p-4 shadow-sm border-l-4 border-l-sky-500">
                    <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Delivered</p>
                    <p class="text-2xl font-bold text-slate-900">{{ m.delivered }}</p>
                </div>
                <div class="glass-card rounded-xl p-4 shadow-sm border-l-4 border-l-teal-500">
                    <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Response Rate</p>
                    <p class="text-2xl font-bold text-teal-600">{{ m.response_rate }}%</p>
                </div>
                <div class="glass-card rounded-xl p-4 shadow-sm border-l-4 border-l-indigo-500">
                    <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Questions</p>
                    <p class="text-2xl font-bold text-slate-900">{{ m.questions }}</p>
                </div>
                <div class="glass-card rounded-xl p-4 shadow-sm border-l-4 border-l-rose-500">
                    <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Escalations</p>
                    <p class="text-2xl font-bold text-rose-600">{{ m.escalations }}</p>
                </div>
                <div class="glass-card rounded-xl p-4 shadow-sm border-l-4 border-l-amber-500">
                    <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Attendance</p>
                    <p class="text-2xl font-bold text-amber-600">{{ m.attendance_rate }}%</p>
                </div>
                <div class="glass-card rounded-xl p-4 shadow-sm border-l-4 border-l-purple-500">
                    <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">AI Confidence</p>
                    <p class="text-2xl font-bold text-purple-600">{{ m.ai_confidence }}%</p>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8">
                <div class="glass-card rounded-2xl p-6 shadow-sm lg:col-span-2">
                    <h3 class="text-sm font-bold text-slate-800 uppercase tracking-wider mb-4">Traffic Volume by Alert Tier</h3>
                    <div class="relative h-64 w-full"><canvas id="barChart"></canvas></div>
                </div>
                <div class="glass-card rounded-2xl p-6 shadow-sm">
                    <h3 class="text-sm font-bold text-slate-800 uppercase tracking-wider mb-4">Proximity Distribution</h3>
                    <div class="relative h-64 w-full flex justify-center items-center"><canvas id="doughnutChart"></canvas></div>
                </div>
            </div>

            <div class="glass-card rounded-2xl shadow-sm overflow-hidden">
                <div class="px-6 py-5 border-b border-slate-100 bg-white">
                    <h3 class="text-sm font-bold text-slate-800 uppercase tracking-wider">Live Execution Logs</h3>
                </div>
                <div class="table-container overflow-x-auto max-h-96">
                    <table class="w-full text-left text-sm whitespace-nowrap">
                        <thead class="bg-slate-50 sticky top-0 z-10 text-xs uppercase font-semibold text-slate-500">
                            <tr>
                                <th class="px-6 py-4 border-b border-slate-200">Course Node</th>
                                <th class="px-6 py-4 border-b border-slate-200">Recipient Node</th>
                                <th class="px-6 py-4 border-b border-slate-200">Alert Tier</th>
                                <th class="px-6 py-4 border-b border-slate-200">Delivery Status</th>
                                <th class="px-6 py-4 border-b border-slate-200">Attn Confirmed</th>
                                <th class="px-6 py-4 border-b border-slate-200">AI Confidence</th>
                                <th class="px-6 py-4 border-b border-slate-200">Timestamp (WAT)</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-100 bg-white">
                            {% if reminders %}
                                {% for r in reminders %}
                                <tr class="hover:bg-slate-50 transition-colors">
                                    <td class="px-6 py-4 font-semibold text-indigo-900">{{ r.event_uid or r.course_code or 'N/A' }}</td>
                                    <td class="px-6 py-4 font-mono text-slate-600">{{ r.phone }}</td>
                                    <td class="px-6 py-4">
                                        {% set raw_t = r.tier | string | upper %}
                                        {% if '24' in raw_t %}
                                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-purple-100 text-purple-800">24 HOURS</span>
                                        {% elif '4' in raw_t %}
                                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-sky-100 text-sky-800">4 HOURS</span>
                                        {% else %}
                                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-800">10 MINS</span>
                                        {% endif %}
                                    </td>
                                    <td class="px-6 py-4">
                                        {% if r.status == 'read' %}
                                            <span class="text-emerald-600 font-medium">✓ Read</span>
                                        {% elif r.status == 'delivered' %}
                                            <span class="text-sky-600 font-medium">✓ Delivered</span>
                                        {% else %}
                                            <span class="text-slate-400">⚡ Dispatched</span>
                                        {% endif %}
                                    </td>
                                    <td class="px-6 py-4 font-bold">
                                        {% if r.is_confirmed == 1 %}
                                            <span class="text-emerald-500">YES</span>
                                        {% else %}
                                            <span class="text-slate-300">-</span>
                                        {% endif %}
                                    </td>
                                    <td class="px-6 py-4 font-mono text-xs font-semibold">
                                        {% if r.ai_confidence is not none %}
                                            {{ (r.ai_confidence * 100) | round(1) }}%
                                        {% else %}
                                            <span class="text-slate-300">N/A</span>
                                        {% endif %}
                                    </td>
                                    <td class="px-6 py-4 text-slate-500">{{ r.sent_at }}</td>
                                </tr>
                                {% endfor %}
                            {% else %}
                                <tr>
                                    <td colspan="7" class="px-6 py-12 text-center text-slate-400 italic">No historical dispatches detected for this timeframe. Listening to real-time streams...</td>
                                </tr>
                            {% endif %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
            const t24 = {{ t24 }}; const t4 = {{ t4 }}; const t10 = {{ t10 }};
            const chartData = [t24, t4, t10];
            const chartColors = ['#7c3aed', '#0ea5e9', '#f59e0b'];

            new Chart(document.getElementById('doughnutChart').getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: ['24 Hours', '4 Hours', '10 Mins'],
                    datasets: [{ data: chartData, backgroundColor: chartColors, borderWidth: 0, hoverOffset: 4 }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, cutout: '75%',
                    plugins: { legend: { position: 'bottom', labels: { usePointStyle: true, padding: 20 } } }
                }
            });

            new Chart(document.getElementById('barChart').getContext('2d'), {
                type: 'bar',
                data: {
                    labels: ['24-Hour Warning', '4-Hour Alert', '10-Min Urgent'],
                    datasets: [{
                        label: 'Dispatched', data: chartData,
                        backgroundColor: ['rgba(124, 58, 237, 0.8)', 'rgba(14, 165, 233, 0.8)', 'rgba(245, 158, 11, 0.8)'],
                        borderRadius: 6, borderSkipped: false
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: true, grid: { color: '#f1f5f9' }, border: { dash: [4, 4] }, ticks: { stepSize: 1 } },
                        x: { grid: { display: false } }
                    },
                    plugins: { legend: { display: false } }
                }
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(
        html_template,
        m=metrics,
        t24=global_tier_counts["24_HOURS"],
        t4=global_tier_counts["4_HOURS"],
        t10=global_tier_counts["10_MINS"],
        reminders=reminders,
        timeframe=timeframe,
    )


# ========================================================
# 4. WHATSAPP QR & SESSION MANAGEMENT
# ========================================================
@app.route("/qr")
def whatsapp_qr():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>WhatsApp Session & QR Scanner</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-100 min-h-screen flex items-center justify-center p-6 text-center font-sans">
        <div class="bg-white p-8 rounded-2xl shadow-xl max-w-md w-full space-y-6 border border-slate-200">
            <div>
                <h1 class="text-2xl font-bold text-slate-800">WhatsApp Connection</h1>
                <p id="status-text" class="text-xs font-semibold uppercase tracking-wider text-indigo-600 mt-1">Checking WAHA Session...</p>
            </div>

            <div id="qr-container" class="min-h-[260px] flex flex-col items-center justify-center bg-slate-50 rounded-xl p-4 border border-dashed border-slate-300 relative">
                <div id="loading-spinner" class="flex flex-col items-center space-y-3">
                    <div class="w-8 h-8 border-4 border-indigo-600 border-t-transparent rounded-full animate-spin"></div>
                    <span id="spinner-text" class="text-xs text-slate-500 font-medium">Communicating with WAHA engine...</span>
                </div>
                <img id="qr-image" src="" alt="WhatsApp QR Code" class="hidden max-w-[220px] rounded shadow-sm border p-2 bg-white" />
                <div id="connected-badge" class="hidden flex-col items-center space-y-2 py-6">
                    <div class="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-full flex items-center justify-center text-3xl font-bold">✓</div>
                    <span class="text-lg font-bold text-emerald-700">Successfully Connected!</span>
                    <span class="text-xs text-slate-500">Bot is active and forwarding events to webhook.</span>
                </div>
            </div>

            <div class="space-y-3 pt-2">
                <a href="/reset-whatsapp" onclick="this.innerHTML='Force Resetting Engine...';" class="block w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 px-4 rounded-xl transition-all shadow-md hover:shadow-lg text-sm">
                    🔄 Force Reset & Generate New QR
                </a>
                <a href="/" class="block w-full bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold py-2.5 px-4 rounded-xl transition-all text-sm">
                    ← Back to Dashboard
                </a>
            </div>
        </div>

        <script>
            async function updateStatus() {
                try {
                    const res = await fetch('/api/session-status');
                    const data = await res.json();
                    const statusText = document.getElementById('status-text');
                    const qrImg = document.getElementById('qr-image');
                    const spinner = document.getElementById('loading-spinner');
                    const spinnerText = document.getElementById('spinner-text');
                    const connectedBadge = document.getElementById('connected-badge');

                    if (data.status === 'WORKING') {
                        statusText.innerText = "● SESSION ACTIVE & CONNECTED";
                        statusText.className = "text-xs font-bold uppercase tracking-wider text-emerald-600 mt-1";
                        spinner.classList.add('hidden');
                        qrImg.classList.add('hidden');
                        connectedBadge.classList.remove('hidden');
                        connectedBadge.classList.add('flex');
                    } else if (data.status === 'SCAN_QR_CODE' || data.status === 'STARTING' || data.status === 'STOPPED') {
                        statusText.innerText = data.status === 'SCAN_QR_CODE' ? "● WAITING FOR SCAN" : "● INITIALIZING ENGINE (" + data.status + ")";
                        statusText.className = "text-xs font-bold uppercase tracking-wider text-amber-600 mt-1";
                        connectedBadge.classList.add('hidden');
                        connectedBadge.classList.remove('flex');
                        
                        const imgRes = await fetch('/api/qr-image?t=' + new Date().getTime());
                        if (imgRes.ok) {
                            const blob = await imgRes.blob();
                            qrImg.src = URL.createObjectURL(blob);
                            qrImg.classList.remove('hidden');
                            spinner.classList.add('hidden');
                        } else {
                            qrImg.classList.add('hidden');
                            spinnerText.innerText = "Generating new QR code from WAHA...";
                            spinner.classList.remove('hidden');
                        }
                    } else {
                        statusText.innerText = "● STATUS: " + (data.status || 'OFFLINE');
                        statusText.className = "text-xs font-bold uppercase tracking-wider text-rose-600 mt-1";
                    }
                } catch (err) {
                    document.getElementById('status-text').innerText = "● CANNOT REACH WAHA ENGINE";
                    document.getElementById('status-text').className = "text-xs font-bold uppercase tracking-wider text-rose-600 mt-1";
                }
            }

            updateStatus();
            setInterval(updateStatus, 3000);
        </script>
    </body>
    </html>
    """


def _create_waha_session():
    """Register the default session pointing webhooks directly to WEBHOOK_URL."""
    headers = {"X-Api-Key": WAHA_KEY} if WAHA_KEY else {}
    session_config = {
        "name": "default",
        "start": True,
        "config": {
            "webhooks": [
                {
                    "url": WEBHOOK_URL,
                    "events": ["message", "message.any"]
                }
            ]
        }
    }
    requests.post(f"{WAHA_URL}/api/sessions", json=session_config, headers=headers, timeout=5)


@app.route("/api/session-status")
def session_status():
    headers = {"X-Api-Key": WAHA_KEY} if WAHA_KEY else {}
    try:
        res = requests.get(f"{WAHA_URL}/api/sessions/default", headers=headers, timeout=5)
        
        if res.status_code == 200:
            return jsonify(res.json())
        
        if res.status_code == 404:
            _create_waha_session()
            return jsonify({"status": "STARTING", "info": f"Created session pointing to {WEBHOOK_URL}"})
            
        return jsonify({"status": "OFFLINE", "error": f"HTTP {res.status_code}"}), res.status_code
    except Exception as e:
        return jsonify({"status": "UNREACHABLE", "error": str(e)}), 502


@app.route("/api/qr-image")
def qr_image_proxy():
    headers = {"X-Api-Key": WAHA_KEY} if WAHA_KEY else {}
    try:
        res = requests.get(f"{WAHA_URL}/api/default/auth/qr?format=image", headers=headers, timeout=5)
        if res.status_code == 200:
            return Response(res.content, mimetype='image/png')
        
        res2 = requests.get(f"{WAHA_URL}/api/sessions/default/auth/qr?format=image", headers=headers, timeout=5)
        if res2.status_code == 200:
            return Response(res2.content, mimetype='image/png')
            
        return "QR Not Ready", 400
    except Exception:
        return "Engine Offline", 502


@app.route("/reset-whatsapp")
def reset_whatsapp():
    headers = {"X-Api-Key": WAHA_KEY} if WAHA_KEY else {}
    
    try:
        requests.post(f"{WAHA_URL}/api/sessions/default/logout", headers=headers, timeout=5)
        requests.post(f"{WAHA_URL}/api/sessions/default/stop", headers=headers, timeout=5)
        requests.delete(f"{WAHA_URL}/api/sessions/default", headers=headers, timeout=5)
    except Exception:
        pass
        
    try:
        _create_waha_session()
    except Exception as e:
        print("Session start error:", e)

    return """
    <!DOCTYPE html>
    <html lang="en">
    <head><title>Resetting WhatsApp Engine...</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-slate-100 min-h-screen flex items-center justify-center p-6 text-center font-sans">
        <div class="bg-white p-8 rounded-2xl shadow-xl max-w-md w-full space-y-4 border border-slate-200">
            <div class="w-12 h-12 bg-indigo-100 text-indigo-600 rounded-full flex items-center justify-center text-2xl mx-auto animate-pulse">🔄</div>
            <h2 class="text-xl font-bold text-slate-800">Session Reset Initiated</h2>
            <p class="text-slate-600 text-sm">Provisioning clean session with webhook listener...</p>
            <div class="w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mx-auto mt-4"></div>
            <script>
                setTimeout(function(){
                    window.location.href = "/qr";
                }, 3500);
            </script>
        </div>
    </body></html>
    """


@app.route("/api/stats")
def api_stats():
    mdb = db.get_db()
    return jsonify(
        total_interactions=mdb.interactions.count_documents({}),
        total_users=mdb.consented_users.count_documents({}),
        total_reminders=mdb.sent_reminders.count_documents({}),
        confirmed=mdb.sent_reminders.count_documents({"is_confirmed": 1}),
        escalated=mdb.sent_reminders.count_documents({"is_escalated": 1}),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"Dashboard running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)