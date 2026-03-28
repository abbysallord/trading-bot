# core/indicators.py — Technical indicator computation
#
# Takes a DataFrame of OHLCV candles and returns it enriched with:
#   - Bollinger Bands (upper, middle/SMA, lower, bandwidth, %B)
#   - RSI
#   - ATR (for dynamic stop-loss sizing in later phases)
#   - Volume SMA (to filter low-liquidity candles)
#
# All indicator logic is stateless — pass in the candle DataFrame,
# get back the same DataFrame with new columns. No side effects.

import pandas as pd
import pandas_ta as ta
from config import BB_PERIOD, BB_STD, RSI_PERIOD


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all technical indicators on a candle DataFrame.

    Input DataFrame must have columns: open, high, low, close, volume
    Returns the same DataFrame with additional indicator columns.

    Drops rows where indicators are NaN (insufficient history).
    """
    if df.empty or len(df) < BB_PERIOD + 5:
        return df

    df = df.copy()

    # ── Bollinger Bands ─────────────────────────────────────────────────────
    # pandas-ta returns: BBL (lower), BBM (middle), BBU (upper)
    # We calculate bandwidth and %B manually
    bb = ta.bbands(df["close"], length=BB_PERIOD, std=BB_STD)
    if bb is not None:
        df["bb_lower"]  = bb[f"BBL_{BB_PERIOD}"]
        df["bb_mid"]    = bb[f"BBM_{BB_PERIOD}"]
        df["bb_upper"]  = bb[f"BBU_{BB_PERIOD}"]
        # Bandwidth: (upper - lower) / middle
        df["bb_width"]  = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
        # %B: (close - lower) / (upper - lower)  [0=at lower, 1=at upper]
        df["bb_pct"]    = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])

    # ── RSI ─────────────────────────────────────────────────────────────────
    rsi = ta.rsi(df["close"], length=RSI_PERIOD)
    if rsi is not None:
        df["rsi"] = rsi

    # ── ATR (Average True Range) ────────────────────────────────────────────
    # Used for dynamic stop-loss: stop = entry - (atr_multiplier * ATR)
    atr = ta.atr(df["high"], df["low"], df["close"], length=14)
    if atr is not None:
        df["atr"] = atr

    # ── Volume SMA ──────────────────────────────────────────────────────────
    # We only trade when volume is above its 20-period average (liquidity filter)
    df["vol_sma"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_sma"]   # >1 means above-average volume

    # ── Simple Moving Averages (for trend-following) ─────────────────────────
    df["sma20"] = df["close"].rolling(20).mean()    # Fast MA (trend direction)
    df["sma50"] = df["close"].rolling(50).mean()    # Slow MA (trend confirmation)

    # ── Drop rows with NaN indicators (insufficient history) ────────────────
    df = df.dropna(subset=["bb_lower", "bb_upper", "rsi", "atr", "sma20", "sma50"]).reset_index(drop=True)

    return df


def get_latest_signals(df: pd.DataFrame) -> dict:
    """
    Extract the most recent row's indicator values as a clean signal dict.
    Call this after compute_indicators() to get the current bar's readings.

    Returns:
        {
            "close":      float,   # latest close price
            "rsi":        float,   # latest RSI value
            "bb_pct":     float,   # 0.0 = at lower band, 1.0 = at upper band
            "bb_lower":   float,
            "bb_upper":   float,
            "bb_mid":     float,
            "bb_width":   float,   # band width % — high = volatile, low = quiet
            "atr":        float,
            "vol_ratio":  float,   # >1 = above-average volume
            "candle_count": int,   # how many candles are in the DataFrame
        }
    """
    if df.empty:
        return {}

    last = df.iloc[-1]
    return {
        "close":       float(last["close"]),
        "rsi":         float(last["rsi"]),
        "bb_pct":      float(last["bb_pct"]),
        "bb_lower":    float(last["bb_lower"]),
        "bb_upper":    float(last["bb_upper"]),
        "bb_mid":      float(last["bb_mid"]),
        "bb_width":    float(last["bb_width"]),
        "atr":         float(last["atr"]),
        "vol_ratio":   float(last["vol_ratio"]),
        "sma20":       float(last["sma20"]),
        "sma50":       float(last["sma50"]),
        "candle_count": len(df),
    }


def describe_market_state(signals: dict) -> str:
    """
    Return a human-readable summary of current market conditions.
    Used for logging and the LLM journaling layer.
    """
    if not signals:
        return "No signal data available."

    rsi       = signals.get("rsi", 50)
    bb_pct    = signals.get("bb_pct", 0.5)
    bb_width  = signals.get("bb_width", 0)
    vol_ratio = signals.get("vol_ratio", 1)
    close     = signals.get("close", 0)

    # RSI interpretation
    if rsi < 30:
        rsi_str = f"RSI {rsi:.1f} — heavily oversold"
    elif rsi < 40:
        rsi_str = f"RSI {rsi:.1f} — oversold"
    elif rsi > 70:
        rsi_str = f"RSI {rsi:.1f} — heavily overbought"
    elif rsi > 60:
        rsi_str = f"RSI {rsi:.1f} — overbought"
    else:
        rsi_str = f"RSI {rsi:.1f} — neutral"

    # BB position
    if bb_pct < 0.1:
        bb_str = f"BB%={bb_pct:.2f} — price at/below lower band"
    elif bb_pct > 0.9:
        bb_str = f"BB%={bb_pct:.2f} — price at/above upper band"
    else:
        bb_str = f"BB%={bb_pct:.2f} — price mid-range"

    # Volatility
    if bb_width < 1.0:
        vol_str = "Low volatility (narrow bands)"
    elif bb_width > 4.0:
        vol_str = "High volatility (wide bands)"
    else:
        vol_str = "Normal volatility"

    # Volume
    v_str = f"Volume {'above' if vol_ratio > 1 else 'below'} average ({vol_ratio:.1f}x)"

    return (f"Price: ₹{close:,.2f} | {rsi_str} | {bb_str} | "
            f"{vol_str} | {v_str}")
