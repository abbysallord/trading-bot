# core/coindcx_api.py — CoinDCX REST API client
#
# Handles authentication and OHLCV data fetching from CoinDCX
# Uses HMAC-SHA256 authentication as per CoinDCX API spec

import os
import json
import time
import hmac
import hashlib
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# CoinDCX API settings
BASE_URL = "https://api.coindcx.com"
API_KEY = os.getenv("COINDCX_API_KEY", "")
SECRET_KEY = os.getenv("COINDCX_SECRET_KEY", "")


class CoinDCXClient:
    """CoinDCX API client for authenticated REST calls"""
    
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.session = requests.Session()
    
    def _get_auth_headers(self, json_body: str = "") -> dict:
        """
        Generate HMAC-SHA256 authenticated headers for CoinDCX.
        
        Signature format: HMAC-SHA256(secret_key, json_body)
        """
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            json_body.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": self.api_key,
            "X-AUTH-SIGNATURE": signature,
        }
        
        return headers

    def get_balances(self) -> list:
        """Fetch all user balances."""
        url = f"{BASE_URL}/exchange/v1/users/balances"
        timestamp = int(round(time.time() * 1000))
        body = {"timestamp": timestamp}
        json_body = json.dumps(body, separators=(',', ':'))
        
        headers = self._get_auth_headers(json_body)
        
        response = self.session.post(url, data=json_body, headers=headers)
        response.raise_for_status()
        return response.json()

    def create_order(self, side: str, symbol: str, quantity: float, price: float) -> dict:
        """
        Place a limit order on CoinDCX.
        We use limit orders to prevent slippage on low volume pairs.
        
        Args:
            side: "buy" or "sell"
            symbol: CoinDCX formatted symbol (e.g. "I-BTC_INR")
            quantity: Amount of base asset to buy/sell
            price: Limit price for the order
        """
        url = f"{BASE_URL}/exchange/v1/orders/create"
        timestamp = int(round(time.time() * 1000))

        body = {
            "side": side.lower(),
            "order_type": "limit_order",
            "market": symbol,
            "price_per_unit": round(price, 4),
            "total_quantity": round(quantity, 6),
            "timestamp": timestamp
        }

        json_body = json.dumps(body, separators=(',', ':'))
        headers = self._get_auth_headers(json_body)
        
        response = self.session.post(url, data=json_body, headers=headers)
        response.raise_for_status()
        return response.json()
    
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 1000) -> pd.DataFrame:
        """
        Fetch OHLCV candles from CoinDCX.
        
        CoinDCX API Note: Public OHLCV data is available at /market_data/candles
        
        Args:
            symbol:    Trading pair (e.g., "BTC/INR")
            timeframe: Candle interval ("1m", "5m", "15m", "1h", "1d")
            limit:     How many candles to fetch
        
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume, datetime
        """
        # Convert symbol: "BTC/INR" to CoinDCX format "I-BTC_INR", "BTC/USDT" to "B-BTC_USDT"
        if "INR" in symbol:
            coin = symbol.split("/")[0]
            pair = f"I-{coin}_INR"
        elif "USDT" in symbol:
            coin = symbol.split("/")[0]
            pair = f"B-{coin}_USDT"
        else:
            pair = symbol.replace("/", "")
        
        # Map timeframes to CoinDCX format
        interval_map = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "4h": "4h",
            "1d": "1d",
        }
        
        if timeframe not in interval_map:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        
        interval = interval_map[timeframe]
        
        # CoinDCX candlestick endpoint
        endpoint = "/market_data/candles"
        
        params = {
            "pair": pair,
            "interval": interval,
            "limit": min(limit, 1000),  # CoinDCX limit: 1000 per request
        }
        
        url = "https://public.coindcx.com" + endpoint
        
        try:
            # Try without authentication first (public endpoint)
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if not data or not isinstance(data, list):
                raise ValueError(f"Invalid response from CoinDCX: {data}")
            
            # Parse CoinDCX format
            ohlcv = []
            for candle in data:
                if isinstance(candle, dict) and "time" in candle:
                    # New format from public endpoint
                    timestamp_ms = int(candle["time"])
                    ohlcv.append([
                        timestamp_ms,
                        float(candle.get("open", 0)),
                        float(candle.get("high", 0)),
                        float(candle.get("low", 0)),
                        float(candle.get("close", 0)),
                        float(candle.get("volume", 0)),
                    ])
                elif isinstance(candle, list) and len(candle) >= 6:
                    # Legacy array format
                    timestamp_ms = int(candle[0]) * 1000 if candle[0] < 10000000000 else int(candle[0])
                    ohlcv.append([
                        timestamp_ms,
                        float(candle[1]),  # open
                        float(candle[2]),  # high
                        float(candle[3]),  # low
                        float(candle[4]),  # close
                        float(candle[5]),  # volume
                    ])
            
            if not ohlcv:
                raise ValueError(f"No OHLCV data returned for {pair}")
            
            # Convert to DataFrame
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            
            return df
        
        except requests.exceptions.RequestException as e:
            raise Exception(f"CoinDCX API error: {str(e)}")


def fetch_ohlcv(symbol: str, timeframe: str = "1m", limit: int = 1000) -> pd.DataFrame:
    """
    Convenience function to fetch OHLCV data from CoinDCX.
    Falls back to Binance if CoinDCX API is unavailable.
    
    Args:
        symbol:    Trading pair (e.g., "BTC/INR")
        timeframe: Candle interval
        limit:     Number of candles to fetch
    
    Returns:
        DataFrame with OHLCV data
    """
    if not API_KEY or not SECRET_KEY:
        print("[CoinDCX] Warning: API credentials not set, attempting public endpoint...")
    
    client = CoinDCXClient(API_KEY, SECRET_KEY)
    
    try:
        return client.fetch_ohlcv(symbol, timeframe, limit)
    except Exception as e:
        # Fallback to Binance
        print(f"[CoinDCX] Error: {str(e)}")
        print(f"[CoinDCX] Falling back to Binance API...")
        
        # Convert INR pair to USDT for Binance
        if "INR" in symbol:
            symbol = symbol.replace("INR", "USDT")
        
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True})
            raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            print(f"[Binance Fallback] Fetched {len(df)} {symbol} candles from Binance")
            return df
        except Exception as binance_error:
            raise Exception(f"Both CoinDCX and Binance failed: {str(binance_error)}")
