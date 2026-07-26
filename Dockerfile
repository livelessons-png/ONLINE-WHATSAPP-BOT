FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py WAHA_INTERACT.py DASHBOARD.py WAHA_REMINDERV2.py mongo_db.py ./
COPY start.sh .
RUN chmod +x start.sh

CMD ["bash", "start.sh"]
