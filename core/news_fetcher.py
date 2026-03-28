# core/news_fetcher.py — Fetches latest crypto headlines for LLM sentiment analysis
import requests
import xml.etree.ElementTree as ET

def get_latest_crypto_headlines(limit: int = 15) -> list[str]:
    """
    Fetches the latest cryptocurrency news headlines from CoinTelegraph's public RSS feed.
    No API key required.
    """
    url = "https://cointelegraph.com/rss"
    headlines = []
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Parse XML
        root = ET.fromstring(response.content)
        
        # The RSS items are inside the <channel> tag
        for item in root.findall('./channel/item'):
            title = item.find('title')
            if title is not None and title.text:
                headlines.append(title.text.strip())
                if len(headlines) >= limit:
                    break
                    
    except Exception as e:
        print(f"[NewsFetcher] Error fetching headlines: {e}")
        # Return fallback generic headlines if network fails so bot doesn't crash
        return ["Bitcoin price stabilizes", "Crypto market remains volatile"]
        
    return headlines

if __name__ == "__main__":
    print("Latest crypto headlines:")
    for h in get_latest_crypto_headlines(5):
        print(f" - {h}")
