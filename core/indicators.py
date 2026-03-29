# core/indicators.py — Technical indicator computation
#
# Takes a DataFrame of OHLCV candles and returns it enriched with:
#   - EMA 9 (Fast Momentum)
#   - EMA 21 (Slow Momentum)
#   - SMA 50 (Baseline Trend)
#   - ATR 14 (For dynamic trailing stop-loss sizing)
#   - Volume SMA (to filter low-liquidity candles)
#
# All indicator logic is stateless — pass in the candle DataFrame,
# get back the same DataFrame with new columns. No side effects.

import numpy as np
np.NaN = np.nan  # Monkeypatch for pandas_ta numpy 2.0 incompatibility

import pandas as pd
if not hasattr(pd.Series, 'append'):
    pd.Series.append = pd.Series._append  # Monkeypatch for pandas 2.0+

import pandas_ta as ta
from config import EMA_FAST, EMA_SLOW, SMA_TREND, ATR_PERIOD, MIN_CANDLES


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all technical indicators on a candle DataFrame.

    Input DataFrame must have columns: open, high, low, close, volume
    Returns the same DataFrame with additional indicator columns.

    Drops rows where indicators are NaN (insufficient history).
    """
    if df.empty or len(df) < MIN_CANDLES + 5:
        return df

    df = df.copy()

    # ── Exponential Moving Averages (Momentum) ──────────────────────────────
    ema_fast = ta.ema(df["close"], length=EMA_FAST)
    if ema_fast is not None:
        df["ema_fast"] = ema_fast
        
    ema_slow = ta.ema(df["close"], length=EMA_SLOW)
    if ema_slow is not None:
        df["ema_slow"] = ema_slow

    # ── Simple Moving Average (Baseline Trend Filter) ────────────────────────
    df["sma_trend"] = df["close"].rolling(SMA_TREND).mean()

    # ── ATR (Average True Range) ────────────────────────────────────────────
    # Used for dynamic trailing mathematical stop-loss
    atr = ta.atr(df["high"], df["low"], df["close"], length=ATR_PERIOD)
    if atr is not None:
        df["atr"] = atr

    # ── Volume SMA ──────────────────────────────────────────────────────────
    # We only trade when volume is above its 20-period average (liquidity filter)
    df["vol_sma"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_sma"]   # >1 means above-average volume

    # ── Drop rows with NaN indicators (insufficient history) ────────────────
    df = df.dropna(subset=["ema_fast", "ema_slow", "sma_trend", "atr", "vol_ratio"]).reset_index(drop=True)

    return df


def get_latest_signals(df: pd.DataFrame) -> dict:
    """
    Extract the most recent row's indicator values as a clean signal dict.
    Call this after compute_indicators() to get the current bar's readings.
    """
    if df.empty:
        return {}

    last = df.iloc[-1]
    return {
        "close":       float(last["close"]),
        "ema_fast":    float(last["ema_fast"]),
        "ema_slow":    float(last["ema_slow"]),
        "sma_trend":   float(last["sma_trend"]),
        "atr":         float(last["atr"]),
        "vol_ratio":   float(last["vol_ratio"]),
        "candle_count": len(df),
    }


def describe_market_state(signals: dict) -> str:
    """
    Return a human-readable summary of current market conditions.
    Used for logging and the LLM journaling layer.
    """
    if not signals:
        return "No signal data available."

    ema_f     = signals.get("ema_fast", 0)
    ema_s     = signals.get("ema_slow", 0)
    sma_t     = signals.get("sma_trend", 0)
    vol_ratio = signals.get("vol_ratio", 1)
    close     = signals.get("close", 0)

    # Momentum state
    if ema_f > ema_s:
        mom_str = "Momentum: BULLISH"
    else:
        mom_str = "Momentum: BEARISH"

    # Trend state
    if close > sma_t:
        trend_str = "Trend: UPTREND"
    else:
        trend_str = "Trend: DOWNTREND"

    # Volume
    v_str = f"Volume {'above' if vol_ratio > 1 else 'below'} avg ({vol_ratio:.1f}x)"

    return (f"Price: ₹{close:,.2f} | {trend_str} | {mom_str} | {v_str}")
