import os
import logging
import asyncio
import json
import base64
import httpx
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from collections import Counter
from typing import Dict, Any, List, Optional
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

# --- DATABASE IMPORTS ---
import firebase_admin
from firebase_admin import credentials, firestore
from telegram import Bot
from telegram.constants import ParseMode
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from google.api_core.exceptions import ResourceExhausted
from supabase import create_client, Client

from solders.pubkey import Pubkey

# ==========================================
# --- 0. KEEP-ALIVE SERVER ---
# ==========================================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hunter is running and hunting!")

def start_server():
    port = int(os.environ.get("PORT", 8080))
    httpd = HTTPServer(("", port), SimpleHandler)
    print(f"--- KEEP-ALIVE: Web server listening on port {port} ---")
    httpd.serve_forever()

def keep_alive():
    t = Thread(target=start_server)
    t.daemon = True
    t.start()

keep_alive()

# --- AGENCY AI BRAIN IMPORTS ---
try:
    from ai_engine import AgencyIntelligence
except ImportError:
    logging.warning("⚠️ ai_engine.py not found. AI Agency Brain disabled.")
    AgencyIntelligence = None

# --- Psych-Ops Division ---
try:
    from social_scanner import SocialScanner
except ImportError:
    logging.warning("⚠️ social_scanner.py not found. Psych-Ops disabled.")
    SocialScanner = None

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger('hunter_v7.0_Full_Agency')

# ==========================================
# --- 1. DUAL DATABASE INITIALIZATION ---
# ==========================================

# A. PRIMARY DB (Users/Config/Active Alerts) - FIREBASE
if os.getenv('FIREBASE_CREDENTIALS_BASE64'):
    try:
        c_p = json.loads(base64.b64decode(os.getenv('FIREBASE_CREDENTIALS_BASE64')))
        cred_p = credentials.Certificate(c_p)
        if not firebase_admin._apps.get('primary'):
            app_p = firebase_admin.initialize_app(cred_p, name='primary')
        else:
            app_p = firebase_admin.get_app('primary')
            
        db = firestore.client(app_p) 
        logger.info("✅ Connected to Primary DB (Firebase: Users/Config)")
    except Exception as e:
        logger.error(f"Primary DB Init Error: {e}")
        db = None
else:
    logger.critical("❌ Missing FIREBASE_CREDENTIALS_BASE64")
    db = None

# B. MAIN SUPABASE DB (Dashboard Data/Tokens)
SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_SERVICE_KEY")
supabase: Client = None

if SUPA_URL and SUPA_KEY:
    try:
        supabase = create_client(SUPA_URL, SUPA_KEY)
        logger.info("✅ Connected to Main Supabase (Dashboard/Tokens)")
    except Exception as e:
        logger.error(f"Supabase Main Init Error: {e}")
else:
    logger.warning("⚠️ Main Supabase keys missing. Dashboard data will NOT be saved.")

# C. RAW DATA SUPABASE DB (Ingestion Source)
SUPA_RAW_URL = os.getenv("SUPABASE_URL_2")
SUPA_RAW_KEY = os.getenv("SUPABASE_SERVICE_KEY_2")
supabase_raw: Client = None

if SUPA_RAW_URL and SUPA_RAW_KEY:
    try:
        supabase_raw = create_client(SUPA_RAW_URL, SUPA_RAW_KEY)
        logger.info("✅ Connected to Raw Supabase (High Speed Ingestion)")
    except Exception as e:
        logger.error(f"Supabase Raw Init Error: {e}")
else:
    logger.critical("❌ Missing SUPABASE_URL_2/KEY_2. Cannot read raw events.")

# --- Securely Load Secrets ---
try:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    MINI_APP_URL = os.getenv('MINI_APP_URL')
    TELEGRAM_ADMIN_CHAT_ID = os.getenv('TELEGRAM_ADMIN_CHAT_ID')
    HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
    GOPLUS_API_KEY = os.getenv("GOPLUS_API_KEY")
    MORALIS_API_KEY = os.getenv("MORALIS_API_KEY")
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID, HELIUS_API_KEY, GOPLUS_API_KEY, MORALIS_API_KEY]):
        raise ValueError("One or more required environment variables are missing.")
except Exception as e:
    logger.critical(f"Hunter could not load secrets: {e}"); sys.exit(1)

# --- NEW: AGENCY AI BRAIN ---
agency_brain = None
try:
    if AgencyIntelligence:
        agency_brain = AgencyIntelligence()
        logger.info("--- 🧠 Agency AI: Online and Ready for Shadow Mode ---")
    else:
        logger.warning("AgencyIntelligence class not imported.")
except Exception as e:
    logger.critical(f"⚠️ CRITICAL: Agency AI failed to load: {e}")
    agency_brain = None

# --- SOCIAL SCANNER INITIALIZATION ---
social_agent = None
if SocialScanner:
    try:
        social_agent = SocialScanner()
        logger.info("--- 🐦 Psych-Ops Division (Social Scanner) Initialized ---")
    except Exception as e:
        logger.error(f"Social Scanner init failed: {e}")

# --- MASTER CONTROL PANEL ---
HUNT_INTERVAL_MINUTES = 10
JANITOR_INTERVAL_HOURS = 1
MAX_INTEL_AGE_HOURS = 12
CREATOR_BLACKLIST = ["7sz9Pxsz5rJmFcUoygywH6ZtxhFvktB8H9C2zP8P1isx"]
KNOWN_SOL_TOKENS = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}
EVM_BURN_ADDRESS = "0x000000000000000000000000000000000000dead"
KNOWN_DEX_ROUTERS = {"0x10ed43c718714eb63d5aa57b78b54704e256024e": "PancakeSwap V2"} 
TREND_SCORE_THRESHOLD = 6 
EVM_TREND_SCORE_THRESHOLD = 4

SOLANA_CONFIG = {
    "min_liquidity_usd": 30000, "max_liquidity_usd": 150000,
    "min_fdv_usd": 150000, "max_fdv_usd": 1000000,
    "min_1h_volume_usd": 80000,
    "min_1h_change_percent": 80, "max_1h_change_percent": 500,
    "whale_liquidity_threshold_usd": 200000,
    "sybil_single_parent_threshold": 3,
    "sybil_multi_cluster_threshold": 2,
    "min_pair_age_hours": 1,
    "max_top_10_holders_pct": 30,
    "min_holders": 50
}
EVM_CONFIG = {
    "min_liquidity_usd": 30000, "max_liquidity_usd": 150000,
    "min_fdv_usd": 150000, "max_fdv_usd": 1000000,
    "min_1h_volume_usd": 80000,
    "min_1h_change_percent": 80, "max_1h_change_percent": 500,
}

bot = Bot(token=TELEGRAM_BOT_TOKEN)
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
MORALIS_API_URL = "https://deep-index.moralis.io/api/v2.2"

# =======================================================
# --- 2. UPDATED HELPER FUNCTIONS (SUPABASE MIRROR) ---
# =======================================================

async def save_alert_to_db(token_data):
    if not supabase:
        logger.warning("❌ Cannot save alert: Main Supabase not connected.")
        return

    try:
        pair_address = token_data.get('pairAddress', '')
        symbol = token_data.get('symbol', 'UNK')
        price = float(token_data.get('priceUsd', 0))
        now_iso = datetime.now(timezone.utc).isoformat()
        
        row = {
            "id": pair_address,
            "symbol": symbol,
            "name": token_data.get('name', 'Unknown'),
            "chain": token_data.get('chain', 'solana'),
            "ca": token_data.get('ca', ''),
            "pairAddress": pair_address,
            "imageUrl": token_data.get('imageUrl', ''),
            "current_price": price,
            "priceAtCall": price,
            "priceUsd": price,
            "peak_price": price,
            "current_gain": 0.0,
            "peak_gain": 0.0,
            "liquidity": float(token_data.get('liquidity', 0)),
            "mcap": float(token_data.get('mcap', 0)),
            "status": "active",
            "risk": "high",
            "timestamp": now_iso,
            "last_updated": now_iso
        }
        
        supabase.table("tokens").upsert(row).execute()
        logger.info(f"⚡ Alert Mirrored to Supabase: {symbol}")
        
    except Exception as e:
        logger.error(f"Failed to save alert to Supabase: {e}")

def get_janitor_state():
    if not db: return {}
    try:
        doc_ref = db.collection('system_state').document('janitor')
        doc = doc_ref.get()
        return doc.to_dict() if doc.exists else {}
    except Exception as e:
        logger.error(f"Failed to get janitor state: {e}")
        return {}

def update_janitor_state():
    if not db: return
    try:
        db.collection('system_state').document('janitor').set({'last_cleanup_at': firestore.SERVER_TIMESTAMP})
    except Exception as e:
        logger.error(f"Failed to update janitor state: {e}")

def get_all_active_subscribers():
    if not db: return [], 0
    try:
        users_ref = db.collection('subscribers').where(filter=firestore.FieldFilter('is_active', '==', True)).stream()
        active_and_unmuted = []
        total_active = 0
        for doc in users_ref:
            total_active += 1
            user_data = doc.to_dict()
            # If alerts_muted is False or missing, they get the alert
            if not user_data.get('alerts_muted', False):
                active_and_unmuted.append(doc.id)
                
        return active_and_unmuted, total_active
    except Exception as e:
        logger.error(f"Failed to get active subscribers: {e}")
        return [], 0

def check_if_alert_exists(chain: str, contract_address: str) -> bool:
    if not db: return True
    doc_id = f"{chain.lower()}-{contract_address.lower()}"
    return db.collection('past_alerts').document(doc_id).get().exists

def save_past_alert(alert_message: str, risk: str, pair_data: dict, master_score: Optional[int] = None, ai_confidence: Optional[float] = None, doc_id: Optional[str] = None):
    if not db: return
    
    if not doc_id:
        doc_id = f"{pair_data['chain'].lower()}-{pair_data['ca'].lower()}"
        
    try:
        current_price = float(pair_data.get('priceUsd', 0))
        
        alert_data = {
            'message': alert_message,
            'risk': risk.lower(),
            'timestamp': firestore.SERVER_TIMESTAMP,
            'status': 'active',
            'entry_price': current_price,
            'current_price': current_price,
            'current_gain': 0.0,
            'peak_price': current_price,
            'peak_gain': 0.0,
            'last_updated_ts': time.time(),
            **pair_data 
        }
        if master_score is not None:
            alert_data['master_score'] = master_score
        if ai_confidence is not None:
            alert_data['ai_confidence'] = ai_confidence
            
        db.collection('past_alerts').document(doc_id).set(alert_data)
        logger.info(f"✅ Alert Saved to Primary DB (History): {pair_data.get('symbol')}")
    except ResourceExhausted:
        logger.warning(f"Quota exceeded; skipped saving alert for {pair_data['ca']}")
    except Exception as e:
        logger.error(f"Failed to save past alert: {e}")

async def send_admin_message(message: str):
    try:
        await bot.send_message(chat_id=TELEGRAM_ADMIN_CHAT_ID, text=message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Failed to send admin message: {e}")

# 🟢 ROBUST DEXSCREENER FETCHER (WITH RETRY & BACKOFF)
async def fetch_pair_data_from_dexscreener(token_address: str, chain: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    retries = 3
    base_delay = 2

    for i in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=30)
            
            # 🟢 SUCCESS
            if r.status_code == 200:
                data = r.json()
                if data.get('pairs'):
                    chain_pairs = [p for p in data['pairs'] if p.get('chainId') == chain]
                    if not chain_pairs:
                        return None
                    
                    # Sort by liquidity to find the main pair
                    best_pair = sorted(chain_pairs, key=lambda x: x.get('liquidity', {}).get('usd', 0), reverse=True)[0]
                    
                    if 'pairCreatedAt' in best_pair:
                        best_pair['pairCreatedAt_dt'] = datetime.fromtimestamp(best_pair['pairCreatedAt'] / 1000, tz=timezone.utc)
                    return best_pair
                return None # No pairs found

            # 🔴 RATE LIMIT HIT (429)
            elif r.status_code == 429:
                wait_time = base_delay * (2 ** i) # 2s, 4s, 8s
                logger.warning(f"⚠️ DexScreener 429 (Rate Limit) for {token_address}. Sleeping {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue # Retry

            # Other errors
            else:
                return None

        except Exception as e:
            logger.error(f"DexScreener fetch failed for {token_address}: {e}")
            await asyncio.sleep(1)
    
    return None

def calculate_master_score(trend_score: int, security_results: dict, is_evm: bool = False) -> (int, str):
    master_score = 0
    breakdown = []
    mint_check = security_results.get('mintable', False) if is_evm else not security_results.get('mint_renounced', False)
    if not mint_check:
        master_score += 30
        breakdown.append("✨ <b>Mint Revoked</b> (+30) 🌟")
    else:
        breakdown.append("Mint Active (+0)")
    freeze_check = security_results.get('is_blacklisted', False) if is_evm else not security_results.get('freeze_renounced', False)
    if not freeze_check:
        master_score += 20
        breakdown.append("🔒 <b>No Freeze/Blacklist</b> (+20) ✅")
    else:
        breakdown.append("Freeze/Blacklist Risk (+0)")
    sybil_type = security_results.get('sybil_details', {}).get('type', 'unknown')
    if sybil_type == 'none':
        master_score += 10
        breakdown.append("🛡️ <b>No Sybil Links</b> (+10) 🌐")
    else:
        breakdown.append("🚨 Sybil Cluster Found (+0)")
    max_score = 6 if not is_evm else 4
    trend_points = round((trend_score / max_score) * 40)
    master_score += trend_points
    breakdown.append(f"🚀 <b>Trend Score: {trend_score}/{max_score}</b> (+{trend_points}) 🎉")
    return master_score, "\n".join(breakdown)

async def get_legend_status(creator_address: str) -> dict:
    if not db or not creator_address: return {}
    try:
        doc = db.collection('creator_hall_of_fame').document(creator_address).get()
        return doc.to_dict() if doc.exists else {}
    except Exception: return {}

async def scan_holders_for_legends(top_holders: list) -> str:
    if not db or not top_holders: return ""
    signals = []
    for holder in top_holders:
        addr = holder.get('address')
        if not addr: continue
        status = await get_legend_status(addr)
        if status.get('status') == 'LEGEND':
            token = status.get('best_token_symbol', 'Unknown')
            signals.append(f"🦄 <b>UNICORN SIGNAL:</b> Creator of <b>${token}</b> is holding this!")
            break 
    return "\n".join(signals)

async def send_high_risk_alert(pair_data: dict, security_results: dict, master_score: int, score_breakdown: str, is_evm: bool = False, extra_signals: str = ""):
    logger.info(f"Attempting to send alert for {pair_data['ca']} on chain {pair_data['chain']}")
    if check_if_alert_exists(pair_data['chain'], pair_data['ca']):
        logger.warning(f"DUPLICATE ALERT for {pair_data['ca']}. Aborting.")
        return

    mcap_value, liquidity_value = pair_data.get('mcap', 0), pair_data.get('liquidity', 0)
    formatted_mcap = f"{mcap_value / 1_000_000:.1f}M" if mcap_value >= 1_000_000 else f"{mcap_value / 1_000:.0f}K"
    formatted_liquidity = f"{liquidity_value / 1_000:.0f}K"
    formatted_price = f"${pair_data.get('priceUsd', 0):.8f}".rstrip('0').rstrip('.')

    message_body = (f"<b>Chain:</b> {pair_data.get('chain').upper()}\n"
                    f"<b>Coin:</b> {pair_data.get('name')} (${pair_data.get('symbol')})\n"
                    f"<b>Liquidity:</b> ${formatted_liquidity}\n<b>Mkt Cap:</b> ${formatted_mcap}\n"
                    f"<b>Current Price:</b> {formatted_price}\n\n"
                    f"{extra_signals}" 
                    f"<b><u>Score Breakdown ({master_score}/100):</u></b>\n{score_breakdown}")

    save_past_alert(message_body, "high", pair_data, master_score)

    try:
        await save_alert_to_db(pair_data)
    except Exception as e:
        logger.error(f"Error saving to Supabase for {pair_data['ca']}: {e}")

    active_unmuted, total_active = get_all_active_subscribers()
    if not active_unmuted:
        logger.warning(f"No active subscribers for {pair_data['ca']}.")
        return

    final_message = f"🔥 <b>High-Risk Alert A New token listed</b> 🔥\n\n{message_body}"
    
    # Safely get the URL, fallback to default if missing
    base_url = os.getenv('MINI_APP_URL', 'https://t.me/MoonshotAlphaBot/app')
    app_url = f"{base_url}?startapp={pair_data['ca']}"
    
    keyboard = [
        [
            InlineKeyboardButton("🚀 Terminal", web_app=WebAppInfo(url=app_url)),
            InlineKeyboardButton("🟢 Alerts: ON", callback_data="toggle_hunter_alerts")
        ],
        [
            InlineKeyboardButton("⭐ Add to Wishlist", callback_data=f'wishlist_add_{pair_data["ca"]}')
        ]
    ]
    keyboard = InlineKeyboardMarkup(keyboard)
    
    sent_count = 0
    for user_id in active_unmuted:
        try:
            await bot.send_message(chat_id=user_id, text=final_message, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            sent_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            pass # Ignoring error log for brevity
            
    admin_confirmation = f"✅ Alert for ${pair_data.get('symbol')} sent to {sent_count}/{total_active} subscribers."
    await send_admin_message(admin_confirmation)

async def send_ai_alert_to_admin(pair_data: dict, verdict: int, confidence: float, reason: str, features: dict):
    if not TELEGRAM_ADMIN_CHAT_ID:
        logger.error("❌ Cannot send AI Alert: TELEGRAM_ADMIN_CHAT_ID is missing.")
        return

    if verdict == 2:
        title, emoji, risk_level = "AGENCY AI: MOONSHOT DETECTED", "🚀", "POTENTIAL GEM"
    elif verdict == 0:
        title, emoji, risk_level = "AGENCY AI: RUG DETECTED", "💀", "HIGH RISK / SCAM"
    else:
        return 

    logger.info(f"Sending AI Intel ({risk_level}) for {pair_data['ca']} to ADMIN.")

    mcap = features.get('market_cap_usd', 0)
    formatted_mcap = f"{mcap / 1_000_000:.1f}M" if mcap >= 1_000_000 else f"{mcap / 1_000:.0f}K"
    
    final_message = (
        f"{emoji} <b>{title}</b> {emoji}\n\n"
        f"<b>Token:</b> {pair_data.get('name')} (${pair_data.get('symbol')})\n"
        f"<b>Address:</b> <code>{pair_data.get('ca')}</code>\n\n"
        f"🧠 <b>AI Verdict:</b> Class {verdict}\n"
        f"🎯 <b>Confidence:</b> {confidence:.1f}%\n"
        f"🔍 <b>Reason:</b> {reason}\n"
        f"----------------------------\n"
        f"📊 <b>Forensic Data:</b>\n"
        f"• Mcap: ${formatted_mcap}\n"
        f"• Liq: ${features.get('liquidity_usd', 0):,.0f}\n"
        f"• Top 10 Holders: {features.get('top_10_holders_pct', 0):.1f}%\n"
        f"• Whale Conc: {features.get('whale_concentration_pct', 0):.2f}\n"
        f"• God Whale Inflow: ${features.get('god_whale_inflow_usd', 0):,.0f}\n"
    )

    dex_url = f"https://dexscreener.com/{pair_data.get('chain')}/{pair_data.get('pairAddress')}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📈 View Chart", url=dex_url)]])
    
    try:
        await bot.send_message(chat_id=TELEGRAM_ADMIN_CHAT_ID, text=final_message, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Failed to send Admin AI alert: {e}")

async def run_database_cleanup():
    # 1. Clean Firebase (Forensics)
    if db:
        logger.info("Janitor: Cleaning Firebase forensics_passed...")
        try:
            now = datetime.now(timezone.utc)
            cleanup_threshold = now - timedelta(hours=MAX_INTEL_AGE_HOURS)
            query = db.collection('forensics_passed').where(
                filter=firestore.FieldFilter('added_at', '<=', cleanup_threshold)
            ).limit(200)
            docs = list(query.stream())
            for doc in docs: doc.reference.delete()
        except Exception as e: logger.error(f"Janitor Firebase Error: {e}")

    # 2. Clean Raw Supabase (Old Events)
    if supabase_raw:
        logger.info("Janitor: Cleaning Supabase Raw events...")
        try:
            # Delete events older than 6 hours from raw db to save space
            cutoff = (datetime.utcnow() - timedelta(hours=6)).isoformat()
            supabase_raw.table("raw_helius_events").delete().lt("created_at", cutoff).execute()
        except Exception as e: logger.error(f"Janitor Supabase Error: {e}")

async def helius_rpc_request(method: str, params: List[Any]) -> Optional[Dict[str, Any]]:
    payload = {"jsonrpc": "2.0", "id": "purity-engine", "method": method, "params": params}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(HELIUS_RPC_URL, json=payload, timeout=45)
            r.raise_for_status()
            data = r.json()
            return data.get("result") if "error" not in data else None
    except Exception as e:
        logger.error(f"Helius RPC call failed for method '{method}': {e}")
        return None

async def get_funding_wallet(address: str):
    signatures_info = await helius_rpc_request("getSignaturesForAddress", [address, {"limit": 1000}])
    if not signatures_info:
        return None
    first_signature = signatures_info[-1]["signature"]
    transaction_details_resp = await helius_rpc_request("getTransaction", [first_signature, {"maxSupportedTransactionVersion": 0}])
    if not transaction_details_resp:
        return None
    for inst in transaction_details_resp.get("transaction", {}).get("message", {}).get("instructions", []):
        if inst.get("programId") == "11111111111111111111111111111111": 
            if inst.get("parsed", {}).get("type") == "transfer":
                if inst["parsed"]["info"]["destination"] == address:
                    return inst["parsed"]["info"]["source"]
    return None

async def check_volume_trend(token_address: str, pair_data: dict) -> bool:
    try:
        volume_1h = pair_data.get('volume', {}).get('h1', 0)
        volume_6h = pair_data.get('volume', {}).get('h6', 0)
        if volume_6h > 0 and (volume_1h / volume_6h) > 5:
            logger.info(f"Volume spike detected for {token_address} (1h: {volume_1h:,.0f} USD, 6h: {volume_6h:,.0f} USD).")
        return True
    except Exception as e:
        logger.error(f"Failed to check volume trend for {token_address}: {e}")
        return True

async def check_rug_filters(pair_data: dict, top_10_holders: List[Dict], total_supply: float) -> bool:
    try:
        burn_address = "11111111111111111111111111111111"
        if not any(h.get('address') == burn_address for h in top_10_holders):
            logger.info(f"Liquidity not burned for {pair_data.get('ca')}")
        else:
            logger.info(f"Liquidity appears burned for {pair_data.get('ca')}")
        return True
    except Exception as e:
        logger.error(f"Rug filter check failed for {pair_data.get('ca')}: {e}")
        return True
        
async def run_purity_engine(token_address: str, pair_data: dict = None):
    results = { 
        "mint_renounced": False, "freeze_renounced": False, 
        "sybil_details": {'type': 'unknown', 'count': 0, 'funder': 'Unknown'}, 
        "holder_distribution_suspicious": False,
        "top_10_holders": [] 
    }
    asset_data = await helius_rpc_request("getAsset", [token_address])
    if asset_data:
        mint_info = asset_data.get("mint_info", {})
        results['mint_renounced'] = mint_info.get("mint_authority") is None
        results['freeze_renounced'] = mint_info.get("freeze_authority") is None
    largest_accounts_resp = await helius_rpc_request("getTokenLargestAccounts", [token_address])
    if not largest_accounts_resp or not largest_accounts_resp.get("value"):
        results['sybil_details']['type'] = 'api_fail'
        return results
    top_accounts_list = largest_accounts_resp["value"][:50]
    top_account_addresses = [acc.get("address") for acc in top_accounts_list]
    accounts_info_resp = await helius_rpc_request("getMultipleAccounts", [top_account_addresses, {"encoding": "base64"}])
    if not accounts_info_resp or not accounts_info_resp.get("value"):
        results['sybil_details']['type'] = 'api_fail'
        return results
    holder_totals = {}
    for i, account_info in enumerate(accounts_info_resp["value"]):
        if not account_info:
            continue
        try:
            raw_data = base64.b64decode(account_info['data'][0])
            owner = str(Pubkey(raw_data[32:64]))
            amount = float(top_accounts_list[i].get("uiAmountString", "0"))
            holder_totals[owner] = holder_totals.get(owner, 0) + amount
        except Exception:
            continue
    sorted_profiles = sorted([{"address": addr, "amount": total} for addr, total in holder_totals.items()], key=lambda x: x["amount"], reverse=True)
    top_10_holders = sorted_profiles[:10]
    results['top_10_holders'] = top_10_holders

    supply_data = await helius_rpc_request("getTokenSupply", [token_address])
    total_supply = float(supply_data["value"]["uiAmountString"]) if supply_data and supply_data.get("value", {}).get("uiAmountString") else 0
    if total_supply > 0:
        LOWER_BOUND_PCT = 0.5
        UPPER_BOUND_PCT = 1.5
        SUSPICIOUS_COUNT_THRESHOLD = 5
        holder_percentages = [(h['amount'] / total_supply) * 100 for h in top_10_holders]
        suspicious_holders_count = sum(1 for pct in holder_percentages if LOWER_BOUND_PCT <= pct <= UPPER_BOUND_PCT)
        if suspicious_holders_count >= SUSPICIOUS_COUNT_THRESHOLD:
            results["holder_distribution_suspicious"] = True
            logger.warning(f"SUSPICIOUS holder distribution for {token_address}. {suspicious_holders_count} of top 10 holders are between {LOWER_BOUND_PCT}% and {UPPER_BOUND_PCT}%.")
    if pair_data:
        await check_volume_trend(token_address, pair_data)
        if total_supply > 0:
            await check_rug_filters(pair_data, top_10_holders, total_supply)
    logger.info(f"Executing Phase 3: Sybil Link Analysis for {token_address}")
    funding_wallets = []
    for holder in top_10_holders:
        funding_wallet = await get_funding_wallet(holder["address"])
        holder["sybil_parent"] = funding_wallet if funding_wallet else "Unknown"
        if funding_wallet:
            funding_wallets.append(funding_wallet)
    funding_counts = Counter(funding_wallets)
    for parent, count in funding_counts.items():
        if count > 1:
            results['sybil_details'] = { 'type': 'cluster', 'count': count, 'funder': parent }
            break
    if not funding_wallets:
        results['sybil_details'] = {'type': 'none', 'count': 0, 'funder': 'None'}
    logger.info(f"Purity Engine results for {token_address}: {results}")
    return results

async def get_goplus_security_data(chain_id: str, token_address: str) -> Optional[Dict]:
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={token_address}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers={"Content-Type": "application/json"}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("code") == 1 and data.get("result"):
            return data["result"].get(token_address.lower())
    except Exception as e:
        logger.error(f"GoPlus API request failed: {e}")
    return None

async def get_moralis_transactions(wallet: str, chain_name: str) -> List[Dict]:
    url = f"https://deep-index.moralis.io/api/v2.2/{wallet}"
    headers = {"accept": "application/json", "X-API-Key": MORALIS_API_KEY}
    params = {"chain": chain_name, "order": "ASC"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, params=params, timeout=45)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        logger.error(f"Moralis API request failed for {wallet}: {e}")
        return []

async def run_evm_purity_engine(token_address: str, chain_name: str, chain_id: str):
    results = {}
    top_holders = []
    security_data = await get_goplus_security_data(chain_id, token_address)
    if not security_data:
        return None, "GoPlus data fetch failed."
    results['mintable'] = security_data.get('mintable') == '1'
    results['is_blacklisted'] = security_data.get('is_blacklisted') == '1'
    top_holders = security_data.get("holders", [])[:10]
    if top_holders:
        funding_wallets = []
        tasks = [get_moralis_transactions(h['address'], chain_name) for h in top_holders]
        for txs in await asyncio.gather(*tasks):
            if txs and txs[0].get("from_address"):
                funding_wallets.append(txs[0]["from_address"])
        counts = Counter(funding_wallets)
        if counts:
            funder, count = counts.most_common(1)[0]
            if count > 1:
                results['sybil_details'] = {'type': 'cluster', 'count': count, 'funder': funder}
    if 'sybil_details' not in results:
        results['sybil_details'] = {'type': 'none'}
    return results, None

async def get_solana_funding_wallet(address: str):
    sigs = await helius_rpc_request("getSignaturesForAddress", [address, {"limit": 1000}])
    if not sigs:
        return None
    tx = await helius_rpc_request("getTransaction", [sigs[-1]["signature"], {"maxSupportedTransactionVersion": 0}])
    if not tx:
        return None
    for inst in tx.get("transaction", {}).get("message", {}).get("instructions", []):
        if inst.get("programId") == "11111111111111111111111111111111" and inst.get("parsed", {}).get("type") == "transfer":
            if inst["parsed"]["info"]["destination"] == address:
                return inst["parsed"]["info"]["source"]
    return None

# --- AI FEATURE GATHERING FUNCTIONS ---

async def calculate_solana_flow(token_address: str, price_usd: float):
    god_inflow = 0.0
    shark_inflow = 0.0
    minnow_outflow = 0.0
    GOD_THRESHOLD = 10000 
    SHARK_THRESHOLD = 1000 

    try:
        sigs = await helius_rpc_request("getSignaturesForAddress", [token_address, {"limit": 50}])
        if not sigs: return 0.0, 0.0, 0.0
        sig_list = [s['signature'] for s in sigs]
        batch_payload = [
            {
                "jsonrpc": "2.0", 
                "id": i, 
                "method": "getTransaction", 
                "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            }
            for i, sig in enumerate(sig_list)
        ]

        async with httpx.AsyncClient() as client:
            resp = await client.post(HELIUS_RPC_URL, json=batch_payload, timeout=45)
            batch_data = resp.json()

        if not isinstance(batch_data, list): return 0.0, 0.0, 0.0

        for item in batch_data:
            if "error" in item or "result" not in item: continue
            tx = item["result"]
            if not tx or "meta" not in tx: continue
            pre_balances = {x['accountIndex']: float(x['uiTokenAmount']['uiAmount'] or 0) 
                           for x in tx['meta']['preTokenBalances'] 
                           if x['mint'] == token_address}
            post_balances = {x['accountIndex']: float(x['uiTokenAmount']['uiAmount'] or 0) 
                             for x in tx['meta']['postTokenBalances'] 
                             if x['mint'] == token_address}

            volume_change = 0
            for idx, post_bal in post_balances.items():
                pre_bal = pre_balances.get(idx, 0)
                diff = post_bal - pre_bal
                if abs(diff) > 0:
                    volume_change += diff
            usd_value = volume_change * price_usd
            if usd_value > 0: # BUY
                if usd_value >= GOD_THRESHOLD:
                    god_inflow += usd_value
                elif usd_value >= SHARK_THRESHOLD:
                    shark_inflow += usd_value
            elif usd_value < 0: # SELL
                abs_val = abs(usd_value)
                if abs_val < SHARK_THRESHOLD:
                    minnow_outflow += abs_val 

        return god_inflow, shark_inflow, minnow_outflow

    except Exception as e:
        logger.error(f"Flow Calc Error for {token_address}: {e}")
        return 0.0, 0.0, 0.0

async def get_solana_ai_features(token_address: str, pair_data: dict) -> Optional[dict]:
    try:
        supply_data = await helius_rpc_request("getTokenSupply", [token_address])
        token_total_supply = float(supply_data["value"]["uiAmountString"]) if supply_data else 0
        if token_total_supply == 0: return None

        largest_accounts_resp = await helius_rpc_request("getTokenLargestAccounts", [token_address])
        current_holders_raw = largest_accounts_resp.get("value", []) if largest_accounts_resp else []
        if not current_holders_raw: return None
        
        current_price_usd = float(pair_data.get('priceUsd', 0))
        god, shark, minnow = await calculate_solana_flow(token_address, current_price_usd)
        
        features = {
            'price_usd': current_price_usd,
            'volume_24h_usd': pair_data.get('volume', {}).get('h24', 0),
            'liquidity_usd': pair_data.get('liquidity', {}).get('usd', 0),
            'market_cap_usd': current_price_usd * token_total_supply,
            'hour_of_day': datetime.now(timezone.utc).hour,
            'god_whale_inflow_usd': god, 
            'shark_whale_inflow_usd': shark, 
            'minnow_outflow_usd': minnow 
        }

        balances = [h['uiAmount'] for h in current_holders_raw[:20]]
        features.update({
            'top_1_holder_pct': (balances[0] / token_total_supply) * 100 if balances else 0,
            'top_10_holders_pct': (sum(balances[:10]) / token_total_supply) * 100 if len(balances) >= 10 else 0,
            'top_20_holders_pct': (sum(balances) / token_total_supply) * 100 if balances else 0
        })
        features['whale_concentration_pct'] = (
            features['top_10_holders_pct'] / features['top_20_holders_pct']
            if features['top_20_holders_pct'] > 0 else 0
        )
        return features

    except Exception as e:
        logger.error(f"Failed to get AI features for SOL {token_address}: {e}")
        return None

async def get_evm_token_supply_from_moralis(token_address: str, chain: str) -> Optional[float]:
    url = f"{MORALIS_API_URL}/erc20/metadata"
    headers = {"Accept": "application/json", "X-API-Key": MORALIS_API_KEY}
    params = {"chain": chain, "addresses": [token_address]}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            if data and isinstance(data, list) and data[0]:
                token_data = data[0]
                total_supply_raw = token_data.get('total_supply')
                decimals = token_data.get('decimals')
                if total_supply_raw and decimals is not None:
                    return float(total_supply_raw) / (10 ** int(decimals))
    except Exception as e:
        logger.error(f"Moralis supply check failed for {token_address} on {chain}: {e}")
    return None

async def get_evm_top_holders_from_moralis(token_address: str, chain: str) -> Optional[List[Dict[str, Any]]]:
    url = f"{MORALIS_API_URL}/erc20/{token_address}/owners"
    headers = {"Accept": "application/json", "X-API-Key": MORALIS_API_KEY}
    params = {"chain": chain, "limit": 20, "order": "DESC"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, params=params, timeout=45)
            r.raise_for_status()
            data = r.json()
            holders = data.get('result', [])
            if not holders and isinstance(data, list): holders = data
            
            standardized_holders = []
            for holder in holders:
                if 'owner_address' in holder and 'balance_formatted' in holder:
                    try:
                        standardized_holders.append({
                            "address": holder['owner_address'],
                            "uiAmount": float(holder['balance_formatted'].replace(',', ''))
                        })
                    except Exception:
                        continue
            return standardized_holders
    except Exception as e:
        logger.error(f"Moralis top holders check failed for {token_address} on {chain}: {e}")
    return None

async def get_evm_ai_features(token_address: str, chain: str, pair_data: dict) -> Optional[dict]:
    try:
        token_total_supply = await get_evm_token_supply_from_moralis(token_address, chain)
        if not token_total_supply or token_total_supply == 0: return None

        current_holders_raw = await get_evm_top_holders_from_moralis(token_address, chain)
        if not current_holders_raw: return None
        
        current_price_usd = float(pair_data.get('priceUsd', 0))

        features = {
            'price_usd': current_price_usd,
            'volume_24h_usd': pair_data.get('volume', {}).get('h24', 0),
            'liquidity_usd': pair_data.get('liquidity', {}).get('usd', 0),
            'market_cap_usd': current_price_usd * token_total_supply,
            'hour_of_day': datetime.now(timezone.utc).hour,
            'god_whale_inflow_usd': 0.0, 
            'shark_whale_inflow_usd': 0.0, 
            'minnow_outflow_usd': 0.0 
        }

        balances = [h['uiAmount'] for h in current_holders_raw[:20]]
        features.update({
            'top_1_holder_pct': (balances[0] / token_total_supply) * 100 if balances else 0,
            'top_10_holders_pct': (sum(balances[:10]) / token_total_supply) * 100 if len(balances) >= 10 else 0,
            'top_20_holders_pct': (sum(balances) / token_total_supply) * 100 if balances else 0
        })
        features['whale_concentration_pct'] = (
            features['top_10_holders_pct'] / features['top_20_holders_pct']
            if features['top_20_holders_pct'] > 0 else 0
        )
        return features

    except Exception as e:
        logger.error(f"Failed to get AI features for EVM {token_address}: {e}")
        return None

# ==========================================
# --- 3. UPDATED HANDSHAKE (SUPABASE) ---
# ==========================================
def execute_hunter_handshake(signature: str, sniper_processed: bool):
    """
    Supabase Version of Handshake:
    - If Sniper is DONE: Delete the row (Clean up).
    - If Sniper is BUSY: Mark 'hunter_processed' as True.
    """
    if not supabase_raw: return

    try:
        if sniper_processed:
            # Both bots done -> Delete row
            supabase_raw.table("raw_helius_events").delete().eq("signature", signature).execute()
        else:
            # Mark processed
            supabase_raw.table("raw_helius_events").update({"hunter_processed": True}).eq("signature", signature).execute()
    except Exception as e:
        logger.error(f"Handshake Error for {signature}: {e}")

# --- MAIN HUNTER LOOP ---
async def hunter_loop():
    logger.info(f"MoonshotAlpha Multi-Chain Hunter v7.0 (Full Agency) Started.")
    while True:
        logger.info(f"--- Hunter starting new analysis cycle ---")
        try:
            janitor_state = get_janitor_state()
            if not janitor_state.get('last_cleanup_at') or (datetime.now(timezone.utc) - janitor_state['last_cleanup_at']) > timedelta(hours=JANITOR_INTERVAL_HOURS):
                await run_database_cleanup()
                update_janitor_state()

            # --- Phase 1: Vetting Solana (FROM SUPABASE RAW) ---
            logger.info("--- Phase 1: Vetting new Solana intel (Supabase) ---")
            try:
                # Polling Supabase for pending events
                response = supabase_raw.table('raw_helius_events')\
                    .select("*")\
                    .eq('hunter_processed', False)\
                    .limit(20)\
                    .execute()
                
                rows = response.data
                
                for row in rows:
                    # 🟢 PACING UPDATE: Slower loop to avoid DexScreener 429
                    await asyncio.sleep(2.0) 
                    
                    signature = row['signature']
                    sniper_done = row.get('sniper_processed', False)
                    raw_event = row.get('raw_event', {})

                    try:
                        creator, token_address = None, None
                        for t in raw_event.get('tokenTransfers',[]):
                            if t.get('mint') not in KNOWN_SOL_TOKENS:
                                creator, token_address = t.get('fromUserAccount'), t.get('mint')
                                break
                        
                        # CHECK 1: Blacklist / No Token Address
                        if not token_address or creator in CREATOR_BLACKLIST:
                            execute_hunter_handshake(signature, sniper_done)
                            continue
                        
                        pair_data = await fetch_pair_data_from_dexscreener(token_address, "solana")
                        
                        # CHECK 2: VALID PAIR DATA
                        # 🟢 REMOVED 'imageUrl' CHECK so we track text-only tokens too.
                        if not pair_data:
                            execute_hunter_handshake(signature, sniper_done)
                            continue
                        
                        # Save to Forensics (Firebase) for tracking
                        db.collection('forensics_passed').document(f"solana-{token_address}").set({
                            'status': 'watching',
                            'chain': 'solana',
                            'token_address': token_address,
                            'creator_address': creator,
                            'pair_address': pair_data.get('pairAddress'),
                            'added_at': firestore.SERVER_TIMESTAMP
                        })
                        
                        # CHECK 3: Success Case
                        execute_hunter_handshake(signature, sniper_done)
                        
                    except Exception as e:
                        logger.error(f"Error vetting Solana row {signature}: {e}")
                        execute_hunter_handshake(signature, sniper_done) 

            except Exception as e:
                logger.error(f"⚠️ Phase 1 (Solana) Supabase Fetch Error: {e}")

            # --- Phase 1: Vetting EVM (Keep Firebase for EVM) ---
            logger.info("--- Phase 1: Vetting new EVM intel (Firebase) ---")
            try:
                weth_variants = ["weth", "wbnb", "weth.e"]
                chain_map = {"bsc": "56", "eth": "1", "base": "8453"}
                pending_evm_docs = db.collection('raw_evm_events').where(filter=firestore.FieldFilter('status', '==', 'pending_vetting')).get()
                for doc in pending_evm_docs:
                    await asyncio.sleep(2.0)
                    try:
                        token = doc.to_dict()
                        chain_name = token.get('chain')
                        token0, token1 = token.get('token0'), token.get('token1')
                        if not all([chain_name, token0, token1]):
                            doc.reference.delete()
                            continue
                        pair0_data = await fetch_pair_data_from_dexscreener(token0, chain_name)
                        is_token0_native = any(v in pair0_data['baseToken']['symbol'].lower() for v in weth_variants) if pair0_data else False
                        target_token_addr = token1 if is_token0_native else token0
                        pair_data = await fetch_pair_data_from_dexscreener(target_token_addr, chain_name)
                        
                        # 🟢 REMOVED 'imageUrl' CHECK here too
                        if not pair_data:
                            doc.reference.delete()
                            continue
                            
                        db.collection('forensics_passed').document(f"{chain_name}-{target_token_addr}").set({
                            'status': 'watching',
                            'chain': chain_name,
                            'token_address': target_token_addr,
                            'pair_address': token.get('pairAddress'),
                            'added_at': firestore.SERVER_TIMESTAMP
                        })
                        doc.reference.delete()
                    except Exception as e:
                        logger.error(f"Error vetting EVM doc {doc.id}: {e}")
                        doc.reference.delete()
            except Exception as e:
                logger.error(f"⚠️ Phase 1 (EVM) DB Fetch Error: {e}")


            # --- Phase 2: DUAL-TRACK Solana Hunt ---
            logger.info("--- Phase 2: Hunting for Solana momentum (Dual-Track) ---")
            try:
                watching_sol = db.collection('forensics_passed').where(filter=firestore.FieldFilter('status', '==', 'watching')).where(filter=firestore.FieldFilter('chain', '==', 'solana')).get()
                for doc in watching_sol:
                    try:
                        token = doc.to_dict()
                        addr = token.get('token_address')
                        creator_addr = token.get('creator_address')
                        
                        creator_status = {}
                        if creator_addr:
                            creator_status = await get_legend_status(creator_addr)
                            if creator_status.get('status') == 'FAILURE':
                                logger.info(f"🚫 SUPPRESSED {addr}: Creator is Blacklisted.")
                                doc.reference.delete()
                                continue
                        
                        if not addr:
                            doc.reference.delete()
                            continue
                        
                        pair_data = await fetch_pair_data_from_dexscreener(addr, "solana")
                        if not pair_data:
                            continue
                        
                        cfg = SOLANA_CONFIG
                        l, f, v, c = (
                            pair_data.get('liquidity', {}).get('usd', 0),
                            pair_data.get('fdv', 0),
                            pair_data.get('volume', {}).get('h1', 0),
                            pair_data.get('priceChange', {}).get('h1', 0)
                        )
                        trend_score = sum([
                            1 if l >= cfg['min_liquidity_usd'] else 0,
                            1 if l <= cfg['max_liquidity_usd'] else 0,
                            1 if f >= cfg['min_fdv_usd'] else 0,
                            1 if f <= cfg['max_fdv_usd'] else 0,
                            1 if v >= cfg['min_1h_volume_usd'] else 0,
                            1 if c >= cfg['min_1h_change_percent'] and c <= cfg['max_1h_change_percent'] else 0
                        ])
                        
                        if trend_score >= TREND_SCORE_THRESHOLD:
                            logger.info(f"--- TREND SCORE PASS: {addr} ({trend_score}/6) ---")
                            sec_res = await run_purity_engine(addr, pair_data) 
                            master_score, breakdown = calculate_master_score(trend_score, sec_res, is_evm=False)
                            
                            extra_signals = ""
                            if creator_status.get('status') == 'LEGEND':
                                extra_signals += f"👑 <b>LEGENDARY CREATOR</b>\nTrack Record: Created <b>${creator_status.get('best_token_symbol')}</b> (MC: ${creator_status.get('best_token_fdv',0)/1000000:.1f}M)\n\n"
                            elif creator_status.get('status') == 'VETERAN':
                                extra_signals += f"✅ <b>VETERAN CREATOR</b>\nTrack Record: Created <b>${creator_status.get('best_token_symbol')}</b>\n\n"
                            
                            unicorn_txt = await scan_holders_for_legends(sec_res.get('top_10_holders', []))
                            if unicorn_txt: extra_signals += f"{unicorn_txt}\n\n"
                            
                            if social_agent:
                                hype_data = await social_agent.get_hype_score(f"${pair_data.get('baseToken', {}).get('symbol')}")
                                if hype_data:
                                    extra_signals += f"🐦 <b>Social Hype:</b> {hype_data['sentiment']}\nScore: {hype_data['score']}/100 | Vol: {hype_data['volume']}\n\n"

                            full_data = {
                                "ca": addr, "chain": "solana", "priceUsd": float(pair_data.get('priceUsd', '0')),
                                "name": pair_data.get('baseToken', {}).get('name'), "symbol": pair_data.get('baseToken', {}).get('symbol'),
                                "mcap": f, "liquidity": l, "pairAddress": pair_data.get('pairAddress'),
                                "imageUrl": pair_data.get('info', {}).get('imageUrl'),
                                "creator_address": creator_addr 
                            }
                            
                            await send_high_risk_alert(full_data, sec_res, master_score, breakdown, is_evm=False, extra_signals=extra_signals)
                            doc.reference.update({'status': 'alerted'})

                        # --- SHADOW MODE (Agency AI) ---
                        if agency_brain and not token.get('ai_alert_sent'):
                            try:
                                raw_features = await get_solana_ai_features(addr, pair_data)
                                if raw_features:
                                    verdict, confidence, reason = agency_brain.analyze_token(raw_features)
                                    should_alert = False
                                    if verdict == 2 and confidence > 50: should_alert = True

                                    if should_alert:
                                        logger.info(f"--- 🤖 AI ALERT TRIGGERED: {addr} (Class {verdict}) ---")
                                        display_data = {
                                            "ca": addr, "chain": "solana", 
                                            "name": pair_data.get('baseToken', {}).get('name'), 
                                            "symbol": pair_data.get('baseToken', {}).get('symbol'),
                                            "pairAddress": pair_data.get('pairAddress')
                                        }
                                        await send_ai_alert_to_admin(display_data, verdict, confidence, reason, raw_features)
                                        doc.reference.update({'ai_alert_sent': True})
                            except Exception as e:
                                logger.error(f"AI Shadow Mode Error for {addr}: {e}")
                        
                        await asyncio.sleep(3)
                    except Exception as e:
                        logger.error(f"Error hunting Solana doc {doc.id}: {e}")
            except Exception as e:
                logger.error(f"⚠️ Phase 2 (Solana) DB Fetch Error: {e}")

            # --- Phase 2: DUAL-TRACK EVM Hunt ---
            logger.info("--- Phase 2: Hunting for EVM momentum (Dual-Track) ---")
            try:
                watching_evm = db.collection('forensics_passed').where(filter=firestore.FieldFilter('status', '==', 'watching')).where(filter=firestore.FieldFilter('chain', 'in', ['bsc', 'eth', 'base'])).get()
                for doc in watching_evm:
                    try:
                        token = doc.to_dict()
                        addr = token.get('token_address')
                        chain_name = token.get('chain')
                        creator_addr = token.get('creator_address', None) 

                        if not addr or not chain_name:
                            doc.reference.delete()
                            continue
                            
                        pair_data = await fetch_pair_data_from_dexscreener(addr, chain_name)
                        if not pair_data:
                            continue
                        
                        cfg = EVM_CONFIG
                        l, f, v, c = (
                            pair_data.get('liquidity', {}).get('usd', 0),
                            pair_data.get('fdv', 0),
                            pair_data.get('volume', {}).get('h1', 0),
                            pair_data.get('priceChange', {}).get('h1', 0)
                        )
                        trend_score = sum([
                            1 for check in [
                                cfg['min_liquidity_usd'] <= l <= cfg['max_liquidity_usd'],
                                cfg['min_fdv_usd'] <= f <= cfg['max_fdv_usd'],
                                v >= cfg['min_1h_volume_usd'],
                                cfg['min_1h_change_percent'] <= c <= cfg['max_1h_change_percent']
                            ] if check
                        ])
                        
                        if trend_score >= EVM_TREND_SCORE_THRESHOLD:
                            logger.info(f"--- TREND SCORE PASS: {addr} ({trend_score}/4) ---")
                            sec_res, err = await run_evm_purity_engine(addr, chain_name, chain_map[chain_name])
                            if err:
                                logger.error(f"EVM Purity Engine failed for {addr}: {err}")
                                continue
                            
                            master_score, breakdown = calculate_master_score(trend_score, sec_res, is_evm=True)
                            
                            evm_signals = ""
                            if social_agent:
                                hype_data = await social_agent.get_hype_score(f"${pair_data.get('baseToken', {}).get('symbol')}")
                                if hype_data:
                                    evm_signals += f"🐦 <b>Social Hype:</b> {hype_data['sentiment']}\nScore: {hype_data['score']}/100 | Vol: {hype_data['volume']}\n\n"

                            full_data = {
                                "ca": addr, "chain": chain_name, "priceUsd": float(pair_data.get('priceUsd', '0')),
                                "name": pair_data.get('baseToken', {}).get('name'), "symbol": pair_data.get('baseToken', {}).get('symbol'),
                                "mcap": f, "liquidity": l, "pairAddress": token.get('pair_address'),
                                "imageUrl": pair_data.get('info', {}).get('imageUrl'),
                                "creator_address": creator_addr 
                            }
                            
                            await send_high_risk_alert(full_data, sec_res, master_score, breakdown, is_evm=True, extra_signals=evm_signals)
                            doc.reference.update({'status': 'alerted'})
                        
                        if agency_brain and not token.get('ai_alert_sent'):
                            try:
                                raw_features = await get_evm_ai_features(addr, chain_name, pair_data)
                                if raw_features:
                                    verdict, confidence, reason = agency_brain.analyze_token(raw_features)
                                    should_alert = False
                                    if verdict == 2 and confidence > 50: should_alert = True

                                    if should_alert:
                                        logger.info(f"--- 🤖 AI ALERT TRIGGERED: {addr} (Class {verdict}) ---")
                                        display_data = {
                                            "ca": addr, "chain": chain_name, 
                                            "name": pair_data.get('baseToken', {}).get('name'), 
                                            "symbol": pair_data.get('baseToken', {}).get('symbol'),
                                            "pairAddress": pair_data.get('pairAddress')
                                        }
                                        await send_ai_alert_to_admin(display_data, verdict, confidence, reason, raw_features)
                                        doc.reference.update({'ai_alert_sent': True})
                            except Exception as e:
                                logger.error(f"AI Shadow Mode Error for {addr}: {e}")
                        
                        await asyncio.sleep(3)
                    except Exception as e:
                        logger.error(f"Error hunting EVM doc {doc.id}: {e}")
            except Exception as e:
                logger.error(f"⚠️ Phase 2 (EVM) DB Fetch Error: {e}")

        except Exception as e:
            logger.critical(f"An error occurred in the main hunter loop: {e}", exc_info=True)

        logger.info(f"Hunter cycle complete. Starting Heartbeat Sleep ({HUNT_INTERVAL_MINUTES} mins)...")
        for i in range(HUNT_INTERVAL_MINUTES):
            await asyncio.sleep(60)
            logger.info(f"💓 Hunter Standby: {i+1}/{HUNT_INTERVAL_MINUTES} minutes elapsed...")

if __name__ == "__main__":
    if db:
        asyncio.run(hunter_loop())
    else:
        logger.critical("Hunter cannot start because Firebase is not initialized.")
