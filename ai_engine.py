import xgboost as xgb
import pandas as pd
import numpy as np
import os
import logging

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('AgencyAI')

class AgencyIntelligence:
    def __init__(self):
        # This MUST match the name of the file you uploaded to GitHub
        self.model_path = "agency_brain_v1.json"
        self.model = None
        
        # The exact features your brain expects (Order is critical!)
        self.features = [
            'liquidity_usd',
            'market_cap_usd',
            'volume_24h_usd',
            'top_1_holder_pct',
            'top_10_holders_pct',
            'top_20_holders_pct',
            'whale_concentration_pct',
            'god_whale_inflow_usd',
            'shark_whale_inflow_usd',
            'minnow_outflow_usd'
        ]
        
        self.load_model()

    def load_model(self):
        """Loads the XGBoost brain from the JSON file."""
        if os.path.exists(self.model_path):
            try:
                self.model = xgb.XGBClassifier()
                self.model.load_model(self.model_path)
                logger.info("✅ AGENCY AI: Online and Ready.")
            except Exception as e:
                logger.critical(f"❌ AGENCY AI ERROR: Could not load model. {e}")
        else:
            logger.critical(f"❌ AGENCY AI ERROR: Brain file '{self.model_path}' not found!")

    def analyze_token(self, token_data):
        """
        Input: Token Data Dict
        Output: (Final_Verdict, Confidence, Reason)
        """
        if not self.model:
            return 0, 0.0, "AI_OFFLINE"

        try:
            # 1. ROBUST DATA PREPARATION
            # Create DataFrame from the dictionary
            input_df = pd.DataFrame([token_data])
            
            # Ensure all expected columns exist (fill missing with 0)
            for col in self.features:
                if col not in input_df.columns:
                    input_df[col] = 0
            
            # STRICTLY reorder columns to match the model's training order
            input_df = input_df[self.features]
            
            # Force all data to float (prevents errors if strings sneak in)
            input_df = input_df.astype(float)
            
            # 2. Run the AI
            pred_class = int(self.model.predict(input_df)[0])
            probs = self.model.predict_proba(input_df)[0]
            ai_confidence = probs[pred_class] * 100

            # ---------------------------------------------------------
            # THE CYBORG LOGIC (Hybrid Overrides)
            # ---------------------------------------------------------
            
            # Rule 1: THE RUG SHIELD
            if pred_class == 0 and ai_confidence > 80:
                return 0, ai_confidence, "AI_RUG_DETECTOR"

            # Rule 2: THE WHALE OVERRIDE
            god_inflow = token_data.get('god_whale_inflow_usd', 0)
            
            if god_inflow > 3000: # $3k Net Buy from God Whales
                if pred_class != 2: 
                    return 2, 85.0, "WHALE_OVERRIDE_AI"
                else:
                    return 2, 99.0, "AI_PLUS_WHALES"

            # Rule 3: THE DUMP PROTECTION
            if god_inflow < -1000: # Whales selling
                if pred_class == 2:
                    return 1, 70.0, "BLOCKED_BY_WHALE_DUMP"

            return pred_class, ai_confidence, "AI_MODEL"
            
        except Exception as e:
            logger.error(f"AI Analysis Failed: {e}")
            return 0, 0.0, "ERROR"
