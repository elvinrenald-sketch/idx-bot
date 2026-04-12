"""
intelligence/scoring.py — Master Conviction Scoring Engine
Aggregates technical, fundamental, pattern anomalies, and AI sentiment to formulate a final "Trade Setup" score (0-100).
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger("idx_bot.scoring")


class ScoringEngine:
    """
    Calculates the final "Conviction Score" and packages the Trade Setup.
    """
    
    def __init__(self, technical_analyzer, fundamental_filter, ai_gemini=None):
        self.ta = technical_analyzer
        self.fund = fundamental_filter
        self.ai = ai_gemini
        
    def evaluate_opportunity(self, ticker: str, current_price: float, anomaly_data: Dict) -> Optional[Dict]:
        """
        Evaluate a single stock anomaly to determine if it meets professional Swing Trading criteria.
        Returns the finalized Trade Setup dictionary or None if discarded by filters.
        """
        logger.info(f"Evaluating {ticker} for professional swing setup...")
        
        # 1. Fundamental Garbage Check
        is_safe, fund_reason, fund_metrics = self.fund.evaluate(ticker)
        if not is_safe:
            logger.info(f"{ticker} dropped: {fund_reason}")
            # If it's a massive anomaly, we might keep it but capped at a low score? 
            # In alpha/pro version, we strictly discard garbage to protect capital.
            return None
            
        # 2. Technical Check
        ta_result = self.ta.analyze(ticker, current_price)
        if "error" in ta_result:
            logger.warning(f"Could not get TA for {ticker}: {ta_result['error']}")
            return None
            
        # 3. Aggregate Base Score
        base_score = 0
        
        # - Anomaly Score Contribution (Max 30)
        magnitude = anomaly_data.get("magnitude", 0)
        anomaly_type = anomaly_data.get("type", "")
        
        if anomaly_type == "VOLUME_PRICE_SPIKE":
            base_score += min(30, int(magnitude * 5))
        elif anomaly_type == "VOLUME_SPIKE":
            base_score += min(20, int(magnitude * 3))
        elif anomaly_type == "PRICE_SPIKE":
            base_score += min(15, int(magnitude * 2))
            
        # - Technical Score Contribution (Max 50)
        ta_score = ta_result.get("score", 0)
        base_score += (ta_score * 0.7) # TA is the core driver for Swing
        
        # - Fundamental Bonus (Max 20)
        fund_bonus = self.fund.get_fundamental_score(fund_metrics)
        base_score += fund_bonus
        
        conviction_score = min(100, int(base_score))
        
        # Trade Decision Filter: 
        # For a professional bot, only output trades with Conviction > 65% 
        # and Risk/Reward > 1.2
        setup = ta_result.get("setup", {})
        rr_ratio = setup.get("risk_reward_ratio", 0)
        
        if conviction_score < 45:
            logger.debug(f"{ticker} scored {conviction_score}. Too low for professional tier.")
            return None
            
        if rr_ratio < 1.2:
            logger.debug(f"{ticker} has poor R/R ratio ({rr_ratio}). Suppressing.")
            return None
            
        # Assemble Final Report Object
        return {
            "ticker": ticker,
            "conviction_score": conviction_score,
            "fundamental_safety": fund_reason,
            "technical_trend": ta_result.get("trend"),
            "technical_signals": ta_result.get("signals", []),
            "setup": setup,
            "anomaly_context": anomaly_data.get("description", ""),
            "has_disclosure": anomaly_data.get("has_disclosure", False)
        }
