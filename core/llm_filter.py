# core/llm_filter.py — Mistral AI filter for market sentiment
import requests
from config import MISTRAL_API_KEY

def get_market_sentiment(headlines: list[str]) -> str:
    """
    Query Mistral AI API for sentiment based on news headlines.
    Returns: "BULLISH", "BEARISH", or "NEUTRAL".
    """
    if not MISTRAL_API_KEY:
        print("[LLM Filter] No MISTRAL_API_KEY found. Defaulting to NEUTRAL.")
        return "NEUTRAL"
        
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {MISTRAL_API_KEY}"
    }
    
    news_text = "\n".join([f"- {h}" for h in headlines])
    
    prompt = (
        "You are an expert Cryptocurrency algorithmic trading filter. "
        "A technical indicator strategy has generated a 'BUY' signal for Bitcoin. "
        "I will provide you with the latest crypto news headlines. "
        "Your job is to read them and decide if there is any catastrophic, majorly negative "
        "news that should cancel the trade (e.g., exchange hacks, major lawsuits, massive government bans), "
        "or if the news is positive/neutral.\n\n"
        "Reply with EXACTLY ONE WORD from this list:\n"
        "BULLISH -> If headlines are positive.\n"
        "BEARISH -> If headlines are catastrophic or strongly negative.\n"
        "NEUTRAL -> If headlines are mixed or regular news.\n\n"
        f"Headlines:\n{news_text}"
    )
    
    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 10
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        reply = data["choices"][0]["message"]["content"].strip().upper()
        
        if "BEARISH" in reply:
            return "BEARISH"
        elif "BULLISH" in reply:
            return "BULLISH"
        else:
            return "NEUTRAL"
    except Exception as e:
        print(f"[LLM Filter] API Error: {e}")
        return "NEUTRAL"

