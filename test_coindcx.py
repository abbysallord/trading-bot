import requests
import os
import time
import hmac
import hashlib
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("COINDCX_API_KEY", "")
secret_key = os.getenv("COINDCX_SECRET_KEY", "")

def test_public():
    print("Testing PUBLIC endpoint with B-BTC_INR")
    url = "https://public.coindcx.com/market_data/candles?pair=B-BTC_INR&interval=5m"
    res = requests.get(url)
    print("Status:", res.status_code)
    try:
        data = res.json()
        print("Data length:", len(data))
        if data:
            print("First item:", data[0])
    except:
        print("Response text:", res.text)

def test_public2():
    print("\nTesting PUBLIC endpoint with I-BTC_INR")
    url = "https://public.coindcx.com/market_data/candles?pair=I-BTC_INR&interval=5m"
    res = requests.get(url)
    print("Status:", res.status_code)
    try:
        data = res.json()
        print("Data length:", len(data))
        if data:
            print("First item:", data[0])
    except:
        print("Response text:", res.text)

def test_auth():
    print("\nTesting AUTH endpoint")
    timestamp = str(int(time.time() * 1000))
    endpoint = "/exchange/v1/markets/candles"
    body = {"pair": "BTCINR", "interval": "5m", "limit": 10}
    # For GET requests, body is usually not in the signature, but CoinDCX sometimes requires it or POST for auth
    # Actually wait, maybe public is POST? No, public is GET.
test_public()
test_public2()
