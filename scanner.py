import os
import logging
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from supabase import create_client, Client

# --- Load Environment Variables ---
load_dotenv()

# --- Basic Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger('field_agent_scanner')
logging.getLogger("waitress").setLevel(logging.ERROR)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# --- NEW DB CONNECTION (RAW STORAGE) ---
# Using _2 credentials for the dedicated Raw Data DB as requested
SUPA_RAW_URL = os.getenv("SUPABASE_URL_2")
SUPA_RAW_KEY = os.getenv("SUPABASE_SERVICE_KEY_2")
supabase_raw: Client = None

try:
    if SUPA_RAW_URL and SUPA_RAW_KEY:
        supabase_raw = create_client(SUPA_RAW_URL, SUPA_RAW_KEY)
        logger.info("✅ Field Agent connected to New Supabase (Raw Storage).")
    else:
        logger.critical("❌ Missing SUPABASE_URL_2 or SUPABASE_SERVICE_KEY_2. Cannot start.")
except Exception as e:
    logger.critical(f"Supabase Connection Failed: {e}")
    supabase_raw = None

# --- Initialize Flask App ---
app = Flask(__name__)

# CONFIGURATION
# "TOKEN_MINT" = God Mode (Detects tokens the moment they are created).
# "CREATE_POOL" = Launch Mode (Detects when liquidity is added).
# Recommendation: Use "TOKEN_MINT" for the raw scanner to capture the earliest possible signal.
EVENT_TYPE_FILTER = "CREATE_POOL"

@app.route('/webhook/helius', methods=['POST'])
def helius_webhook_handler():
    """Receives events from Helius and dumps them into the Raw DB."""
    if not supabase_raw:
        return jsonify({"error": "Raw DB down"}), 500

    events = request.json
    
    # Helius sometimes sends a single dict, sometimes a list. Handle both.
    if isinstance(events, dict):
        events = [events]
        
    if isinstance(events, list):
        logger.info(f"Received {len(events)} events.")
        
        payloads = []
        for event in events:
            # Filter for the specific event type (Mint or Pool)
            if event.get("type") == EVENT_TYPE_FILTER:
                signature = event.get('signature')
                if signature:
                    payloads.append({
                        "signature": signature,
                        "raw_event": event,
                        "sniper_processed": False,
                        "hunter_processed": False
                    })

        # Bulk Insert Logic
        if payloads:
            try:
                # ⚡ Bulk Insert (upsert=True ignores duplicates based on primary key 'signature')
                data = supabase_raw.table("raw_helius_events").upsert(payloads).execute()
                logger.info(f"✅ Saved {len(payloads)} events to Raw DB.")
            except Exception as e:
                logger.error(f"Save Error: {e}")
                # Optional: You could write to a backup local file here if DB fails

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    if supabase_raw:
        from waitress import serve
        port = int(os.environ.get('PORT', 8080))
        logger.info(f"Field Agent Scanner online on port {port}")
        serve(app, host='0.0.0.0', port=port)
    else:
        logger.critical("Scanner cannot start without Database connection.")
