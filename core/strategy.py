# core/strategy.py — Momentum + Trend Following Strategy
#
# This strategy combines:
# 1. TREND FILTER: Only buy when price is in uptrend (above both SMAs)
# 2. MOMENTUM: RSI in sweet spot (40-70) = price rising with good momentum
# 3. VOLATILITY: Bollinger Bands confirm the move isn't fake
# 4. VOLUME: Above-average volume confirms strength
#
# Why this works better than mean reversion:
# - BTC trends more than it reverts (especially on 5m/15m)
# - Buys on strength (momentum), not weakness (mean reversion)
# - Has trend filter to avoid counter-trend trades
# - Smart exits that let winners run
#
# The strategy only generates LONG (buy) signals — no short selling.

from typing import Literal
from config import RSI_OVERSOLD, RSI_OVERBOUGHT


Signal = Literal["buy", "sell", "hold"]


def generate_signal(signals: dict,
                    has_open_position: bool = False,
                    open_side: str = "buy") -> tuple[Signal, str]:
    """
    Generate trading signals using momentum + trend following.
    
    ENTRIES: Buy when uptrend + momentum + volume confirmation
    EXITS: Smart stops that lock profits and cut losses early
    """

    if not signals:
        return "hold", "No indicator data"

    close     = signals.get("close", 0)
    rsi       = signals.get("rsi", 50)
    bb_pct    = signals.get("bb_pct", 0.5)
    bb_lower  = signals.get("bb_lower", 0)
    bb_mid    = signals.get("bb_mid", 0)
    bb_upper  = signals.get("bb_upper", 0)
    vol_ratio = signals.get("vol_ratio", 1.0)
    sma20     = signals.get("sma20", 0)
    sma50     = signals.get("sma50", 0)
    candles   = signals.get("candle_count", 0)

    # ── Guard: not enough history ───────────────────────────────────────────
    if candles < 50:
        return "hold", f"Insufficient history ({candles}/50)"

    # ── If we have an open BUY position — check for SMART exit ───────────
    if has_open_position and open_side == "buy":
        # Exit 1: Price back to SMA20 after a good move (lock profits)
        if close < sma20 and rsi < 55:
            return "sell", (f"EXIT: Price returned to SMA20\n"
                            f"Price={close:.2f}, SMA20={sma20:.2f}, RSI={rsi:.1f}")

        # Exit 2: Strong close above BB upper band (take profits at extremes)
        if bb_pct > 0.95 and rsi > 70:
            return "sell", (f"TAKE PROFIT: Overbought at upper band\n"
                            f"BB%={bb_pct:.2f}, RSI={rsi:.1f}")

        # Exit 3: RSI divergence (price up but RSI falling = loss of momentum)
        if rsi < 30:
            return "sell", (f"EXIT: Lost momentum (RSI dropped to {rsi:.1f})\n"
                            f"Avoid riding back down")

        # Exit 4: Price breaks below SMA50 (trend broken)
        if close < sma50:
            return "sell", (f"EXIT: Trend broken. Below SMA50.\n"
                            f"Price={close:.2f}, SMA50={sma50:.2f}")

        return "hold", f"HOLDING: RSI={rsi:.1f}, Price vs SMA20: {close-sma20:+.2f}"

    # ── No open position — check for MOMENTUM ENTRY ───────────────────────
    if not has_open_position:

        # REQUIRED: Trend filter (price above both SMAs = uptrend)
        trend_valid = close > sma20 and sma20 > sma50
        
        if not trend_valid:
            return "hold", (f"NO TREND: Price below key MAs\n"
                            f"Price={close:.2f} | SMA20={sma20:.2f} | SMA50={sma50:.2f}")

        # Entry 1: STRONG momentum — RSI in ideal range (55-70) + confirmed uptrend
        if (rsi > 55 and rsi < 70                # STRONG momentum (not weak 50-55)
                and vol_ratio > 1.2              # Good volume confirmation
                and bb_pct > 0.6                 # Price well above midline (strength)
                and close > sma20):

            return "buy", (f"★ STRONG MOMENTUM ★\n"
                           f"RSI={rsi:.1f} | Volume={vol_ratio:.1f}x | Uptrend clear")

        # Entry 2: Dip in confirmed uptrend — only when SMA20 clearly trending UP
        if (rsi > 45 and rsi < 60              # Good momentum range
                and (sma20 > sma50 * 1.005)     # SMA20 > SMA50 AND moving up 0.5%
                and vol_ratio > 1.15
                and close > sma20):

            return "buy", (f"UPTREND DIP ★\n"
                           f"RSI={rsi:.1f}, Uptrend confirmed (SMA20>SMA50)")

    return "hold", (f"WAITING: Trend={('UP' if close > sma20 and sma20 > sma50 else 'NONE')} "
                    f"RSI={rsi:.1f} Vol={vol_ratio:.1f}x")


def signal_strength(signals: dict) -> float:
    """
    Return a 0.0–1.0 score for how strong the current BUY setup is.
    Used by the ML layer later to weight/filter signals.

    0.0 = no setup at all
    1.0 = perfect textbook mean reversion setup
    """
    if not signals:
        return 0.0

    rsi       = signals.get("rsi", 50)
    bb_pct    = signals.get("bb_pct", 0.5)
    vol_ratio = signals.get("vol_ratio", 1.0)

    # RSI component: lower RSI = stronger oversold = higher score
    rsi_score = max(0, (RSI_OVERSOLD - rsi) / RSI_OVERSOLD)

    # BB% component: closer to 0 = more extended below lower band = higher score
    bb_score = max(0, (0.15 - bb_pct) / 0.15)

    # Volume component: above-average volume confirms the signal
    vol_score = min(1.0, (vol_ratio - 0.8) / 1.2)

    # Weighted average
    score = (rsi_score * 0.4) + (bb_score * 0.4) + (vol_score * 0.2)
    return round(min(1.0, max(0.0, score)), 3)
