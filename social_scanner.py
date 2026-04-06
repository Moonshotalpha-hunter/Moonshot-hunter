import asyncio
import logging
import os
import json  # <--- FIXED: Added missing import
from datetime import datetime, timezone
from twikit import Client
from dotenv import load_dotenv

# --- Load Secrets ---
load_dotenv()

# --- Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger('social_scanner_v1')

class SocialScanner:
    def __init__(self):
        # Initialize client with English language
        self.client = Client('en-US')
        self.is_logged_in = False

    async def load_session(self):
        """
        Loads cookies from the manual cookies.json file.
        Bypasses Cloudflare by using an existing browser session.
        """
        try:
            logger.info("🍪 Loading manual session from cookies.json...")
            
            if not os.path.exists('cookies.json'):
                logger.error("❌ cookies.json not found! You must create this file manually.")
                return False

            self.client.load_cookies('cookies.json')
            self.is_logged_in = True
            logger.info("✅ Session loaded successfully.")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to load cookies: {e}")
            return False

    async def get_hype_score(self, ticker_symbol: str):
        """
        Searches for the ticker (e.g., $PEPE) and calculates a quick hype score.
        """
        if not self.is_logged_in:
            success = await self.load_session()
            if not success: return None

        query = f"{ticker_symbol} lang:en -filter:links" # Search symbol, English only
        logger.info(f"🔎 Scanning Socials for: {query}")

        try:
            # Search for 'Latest' tweets to gauge real-time reaction
            tweets = await self.client.search_tweet(query, product='Latest', count=20)
            
            if not tweets:
                return {"score": 0, "sentiment": "DEAD", "volume": "None"}

            # --- SIMPLE ANALYSIS ---
            total_engagement = 0
            tweet_texts = []

            for tweet in tweets:
                # Twikit returns objects, we access attributes directly
                # Check if attributes exist to avoid errors
                likes = getattr(tweet, 'favorite_count', 0)
                retweets = getattr(tweet, 'retweet_count', 0)
                text = getattr(tweet, 'text', '')
                
                total_engagement += (likes + retweets)
                tweet_texts.append(text)

            # Normalize Score (Arbitrary 'Hype' Math)
            # 20 tweets * 10 engagement avg = 200 score (Medium Hype)
            hype_score = min(100, int(total_engagement / 5)) 
            
            # Simple Keyword Sentiment
            bullish_keywords = [
    "lfg", "gm", "moon", "to the moon", "send it", "ape", "aping", "bullish",
    "wen lambo", "lambo", "mooning", "send", "liftoff", "🚀", "📈",
    "diamond hands", "hodl", "hodling", "strong hands", "load up",
    "buy the dip", "btd", "accumulating", "100x", "gem", "mega gem",
    "parabolic", "breakout", "next shiba", "next bono", "we're early",
    "ATH", "new ATH", "all-time high", "whales buying", "floor rising",
    "green candles", "partnership", "listing", "major listing",
    "launch confirmed", "mainnet live", "alpha", "pump it",
    "bull market", "bull run", "flippening"
]

            bearish_keywords = [
    "rug", "rugged", "rug pull", "scam", "honeypot", "fake", "fraud",
    "dump", "dumping", "exit liquidity", "dead coin", "rekt", "ngmi",
    "sell-off", "panic selling", "weak hands", "bags", "bag holder",
    "liquidity gone", "no liquidity", "devs gone", "dev sold",
    "contract exploit", "hack", "drained", "exit scam", "red candles",
    "chart dying", "no buyers", "taxes too high", "locked trading",
    "unlock event", "rug alert", "whale sold", "failed project"
]

            
            bull_count = sum(1 for t in tweet_texts if any(k in t.lower() for k in bullish_keywords))
            bear_count = sum(1 for t in tweet_texts if any(k in t.lower() for k in bearish_keywords))

            sentiment = "NEUTRAL"
            if bull_count > bear_count * 2: sentiment = "🔥 BULLISH"
            if bear_count > 0: sentiment = "⚠️ RISKY" 

            return {
                "score": hype_score,
                "sentiment": sentiment,
                "volume": f"{len(tweets)} recent tweets",
                "sample_tweet": tweet_texts[0][:50] + "..." if tweet_texts else ""
            }

        except Exception as e:
            logger.error(f"Social Scan Error: {e}")
            return None

# --- Test Execution ---
if __name__ == "__main__":
    async def test():
        scanner = SocialScanner()
        # Test with a popular coin to ensure we get results
        result = await scanner.get_hype_score("$Catholic") 
        
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("Failed to get result.")
    

    asyncio.run(test())
