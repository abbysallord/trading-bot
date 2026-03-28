#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from core.coindcx_api import fetch_ohlcv
from core.indicators import compute_indicators, get_latest_signals
from config import SYMBOL, TIMEFRAME

# Fetch data
print(f"\n[DEBUG] Fetching {500} candles for {SYMBOL} on {TIMEFRAME}...")
df = fetch_ohlcv(SYMBOL, TIMEFRAME, 500)

if df.empty:
    print("[ERROR] No data fetched!")
    sys.exit(1)

print(f"[DEBUG] Fetched {len(df)} candles")

# Compute indicators
df = compute_indicators(df)

print(f"[DEBUG] After indicators: {len(df)} rows (dropped {500 - len(df)} NaN rows)")

if df.empty:
    print("[ERROR] No data after computing indicators!")
    sys.exit(1)

# Show recent 10 rows  
print("\n[DEBUG] LAST 10 ROWS:")
print("=" * 120)
print(df[["close", "rsi", "sma20", "sma50", "bb_pct", "vol_ratio"]].tail(10).to_string())
print("=" * 120)

# Show the latest signal
signals = get_latest_signals(df)
print("\n[DEBUG] LATEST SIGNALS:")
for key, value in signals.items():
    if key == "candle_count":
        continue
    print(f"  {key:20s} = {value:10.2f}")

# Check conditions
print("\n[DEBUG] CONDITIONS CHECK:")
rsi = signals["rsi"]
sma20 = signals["sma20"]
sma50 = signals["sma50"]
close = signals["close"]
vol_ratio = signals["vol_ratio"]
bb_pct = signals["bb_pct"]
atr = signals["atr"]

print(f"  In uptrend (SMA20 > SMA50):  {sma20} > {sma50} = {sma20 > sma50}")
print(f"  Price > SMA20:               {close} > {sma20} = {close > sma20}")
print(f"  RSI in range (35-75):        {rsi} in 35-75 = {35 < rsi < 75}")
print(f"  RSI oversold (< 40):         {rsi} < 40 = {rsi < 40}")
print(f"  BB% oversold (< 0.30):       {bb_pct} < 0.30 = {bb_pct < 0.30}")
print(f"  Volume above 0.8x:           {vol_ratio} > 0.8 = {vol_ratio > 0.8}")

# Why no entry?
print("\n[DEBUG] ENTRY ANALYSIS:")
if not (sma20 > sma50):
    print("  ❌ NO ENTRY: Market is in DOWNTREND (SMA20 < SMA50)")
elif not (close > sma20):
    print("  ❌ NO ENTRY: Price below SMA20 (not in uptrend yet)")
elif not (35 < rsi < 75):
    print(f"  ❌ NO ENTRY: RSI={rsi:.0f} outside range 35-75")
else:
    print("  ✓ Momentum entry conditions met!")

if rsi < 40 and bb_pct < 0.30 and vol_ratio > 0.8 and close > sma50:
    print("  ✓ Mean reversion entry conditions met!")
elif rsi < 40:
    print(f"  ❌ NO MR ENTRY: RSI < 40 OK, but BB%={bb_pct:.3f} > 0.30 or Vol={vol_ratio:.2f}x < 0.8")
