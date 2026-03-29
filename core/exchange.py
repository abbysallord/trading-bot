# core/exchange.py — CoinDCX connection (Custom API wrapper)
#
# Responsibilities:
#   1. Fetch historical OHLCV candles (REST) for backtesting + warm-up
#   2. Stream live 1-minute candles (WebSocket polling fallback)
#   3. Place and cancel orders (paper mode short-circuits before API call)
#

import asyncio
import time
import requests
from typing import Callable, Optional
from config import (
    API_KEY, SECRET_KEY, SYMBOLS, TIMEFRAME,
    TRADING_MODE, TAKER_FEE
)
from core.database import insert_candle, insert_candles_bulk, get_candle_count
from core.coindcx_api import fetch_ohlcv, CoinDCXClient
import pandas as pd

# ── Historical data ─────────────────────────────────────────────────────────

def fetch_historical_candles(symbol: str,
                              timeframe: str = TIMEFRAME,
                              limit: int = 500) -> pd.DataFrame:
    """
    Fetch up to `limit` historical OHLCV candles via REST.
    Stores them in SQLite and returns a DataFrame.

    Call this on startup to warm up the indicator engine before
    the live feed begins.
    """
    print(f"[Exchange] Fetching {limit} historical candles for {symbol}...")

    try:
        df = fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as e:
        print(f"[Exchange] Error fetching history: {e}")
        return pd.DataFrame()

    if df.empty:
        print("[Exchange] No historical data returned.")
        return pd.DataFrame()

    # Persist to SQLite (deduped automatically)
    inserted = insert_candles_bulk(symbol, df)
    total    = get_candle_count(symbol)
    print(f"[Exchange] Stored {inserted} new candles. Total in DB: {total}")

    return df


# ── Live feed (polling) ─────────────────────────────────────────────────────

async def live_candle_feed(symbols: list[str] = SYMBOLS,
                           timeframe: str = TIMEFRAME,
                           on_candle: Callable[[dict], None] = None,
                           poll_interval: int = 15) -> None:
    """
    Poll CoinDCX every `poll_interval` seconds for the latest closed candle 
    for each symbol in the symbols list.
    """
    last_ts = {sym: None for sym in symbols}

    print(f"[Feed] Starting live candle feed for {symbols} ({timeframe})...")
    print(f"[Feed] Polling every {poll_interval}s.")

    while True:
        for sym in symbols:
            try:
                df = fetch_ohlcv(sym, timeframe=timeframe, limit=3)
                if df.empty or len(df) < 2:
                    continue

                # df.iloc[-2] is the last CLOSED candle
                closed = df.iloc[-2]
                ts = int(closed["timestamp"])
                o = float(closed["open"])
                h = float(closed["high"])
                l = float(closed["low"])
                c = float(closed["close"])
                v = float(closed["volume"])

                if ts != last_ts[sym]:
                    last_ts[sym] = ts

                    # Persist to DB
                    insert_candle(sym, ts, o, h, l, c, v)

                    candle = {
                        "symbol":    sym,
                        "timestamp": ts,
                        "open":      o,
                        "high":      h,
                        "low":       l,
                        "close":     c,
                        "volume":    v,
                        "datetime":  pd.Timestamp(ts, unit="ms"),
                    }

                    print(f"[Feed] New candle [{sym}]: {candle['datetime']}  "
                          f"O={o:.4f} H={h:.4f} L={l:.4f} C={c:.4f} V={v:.4f}")

                    if on_candle:
                        on_candle(candle)

            except Exception as e:
                print(f"[Feed] Error fetching live candle for {sym}: {e}")

        await asyncio.sleep(poll_interval)


# ── Order execution ─────────────────────────────────────────────────────────

def place_order(symbol: str, side: str, quantity: float,
                order_type: str = "market") -> dict:
    """
    Place a buy or sell order.

    In PAPER mode: logs the order and returns a simulated fill.
    In LIVE mode:  Not implemented.
    """
    if TRADING_MODE == "paper":
        fill_price = get_current_price(symbol)
        if fill_price == 0.0:
            print("[Order] Error getting current price for paper trade!")
            # Use a dummy price to avoid crashing
            fill_price = 1.0

        fee_inr = fill_price * quantity * TAKER_FEE

        result = {
            "id":       f"PAPER-{int(time.time()*1000)}",
            "price":    fill_price,
            "filled":   quantity,
            "fee":      fee_inr,
            "mode":     "paper",
        }
        print(f"[Order] PAPER {side.upper()} {quantity:.6f} {symbol} "
              f"@ ₹{fill_price:.2f}  fee=₹{fee_inr:.4f}")
        return result

    else:
        # LIVE order
        print(f"[Order] Initiating LIVE Limit {side.upper()} order for {symbol}...")
        try:
            fill_price = get_current_price(symbol)
            if fill_price == 0.0:
                print("[Order] Error getting current price for live trade, aborting.")
                return {}
                
            # Convert symbol: "BTC/INR" to CoinDCX format "I-BTC_INR"
            if "INR" in symbol:
                coin = symbol.split("/")[0]
                pair = f"I-{coin}_INR"
            elif "USDT" in symbol:
                coin = symbol.split("/")[0]
                pair = f"B-{coin}_USDT"
            else:
                pair = symbol.replace("/", "")
                
            client = CoinDCXClient(API_KEY, SECRET_KEY)
            
            # Aggressive Limit Order (Market-Taker execution with max 0.3% slippage protection)
            aggressive_price = fill_price * 1.003 if side == "buy" else fill_price * 0.997
            
            response = client.create_order(side=side, symbol=pair, quantity=quantity, price=aggressive_price)
            
            if "orders" in response and len(response["orders"]) > 0:
                order_id = response["orders"][0].get("id", f"LIVE-{int(time.time()*1000)}")
            else:
                order_id = response.get("id", f"LIVE-{int(time.time()*1000)}")
            
            fee_inr = fill_price * quantity * TAKER_FEE
            result = {
                "id":       order_id,
                "price":    fill_price,
                "filled":   quantity,
                "fee":      fee_inr,
                "mode":     "live",
                "raw":      response
            }
            print(f"[Order] LIVE {side.upper()} {quantity:.6f} {symbol} "
                  f"@ ₹{fill_price:.2f}  fee=₹{fee_inr:.4f} placed successfully.")
            return result
        except Exception as e:
            print(f"[Order] LIVE order execution failed: {e}")
            return {}


def get_current_price(symbol: str) -> float:
    """Fetch the latest traded price for a symbol."""
    if "INR" in symbol:
        coin = symbol.split("/")[0]
        pair = f"I-{coin}_INR"
    elif "USDT" in symbol:
        coin = symbol.split("/")[0]
        pair = f"B-{coin}_USDT"
    else:
        pair = symbol.replace("/", "")
        
    try:
        url = f"https://public.coindcx.com/market_data/candles?pair={pair}&interval=1m&limit=1"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            if isinstance(data[0], dict) and "close" in data[0]:
                return float(data[0]["close"])
            elif isinstance(data[0], list) and len(data[0]) > 4:
                return float(data[0][4])
    except Exception as e:
        print(f"[Exchange] Error fetching current price: {e}")
        
    # Fallback
    try:
        import ccxt
        exchange = ccxt.binance()
        binance_symbol = symbol.replace("INR", "USDT")
        ticker = exchange.fetch_ticker(binance_symbol)
        return float(ticker["last"])
    except Exception:
        return 0.0


def get_account_balance() -> dict:
    """
    Fetch all active balances dynamically via authenticated CoinDCX API.
    """
    balances = {"INR": 0.0}
    try:
        client = CoinDCXClient(API_KEY, SECRET_KEY)
        response = client.get_balances()
        
        if isinstance(response, list):
            for item in response:
                currency = item.get("currency")
                balance_val = float(item.get("balance", "0.0"))
                if currency and balance_val > 0.0:
                    balances[currency] = balance_val
                elif currency == "INR":
                    balances[currency] = balance_val # Ensure INR is always tracked even if 0
        
        return balances
    except Exception as e:
        print(f"[Exchange] Live account balance fetch failed: {e}")
        return balances
