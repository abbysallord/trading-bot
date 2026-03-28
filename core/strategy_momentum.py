# core/strategy_momentum.py — Trend-Following Strategy for BTC
# 
# This works BETTER than mean reversion for BTC because:
# 1. BTC has strong directional trends (momentum)
# 2. Lower entry price (SMA20 > SMA50)
# 3. Clear exit signals (trend breaks)
# 4. Much higher win rates
#
# ENTRY Signal (UPTREND):
#   - Price crosses/bounces above SMA20 (fast MA)
#   - SMA20 > SMA50 (confirmed uptrend)
#   - RSI between 40-60 (not oversold, not overheated)
#   - Volume above average (confirmation)
#
# EXIT Signal (TREND BREAK):
#   - Price closes below SMA20 (trend broken)
#   - RSI > 70 (overbought - take profits)
#   - Price > SMA50 + 2*ATR (take profits on strong move)

from typing import Literal

Signal = Literal["buy", "sell", "hold"]


def generate_signal(signals: dict,
                    has_open_position: bool = False,
                    open_side: str = "buy",
                    entry_price: float = None) -> tuple[Signal, str]:
    """
    Trend-following strategy for trending assets like BTC.
    """

    if not signals:
        return "hold", "No data"

    close      = signals.get("close", 0)
    rsi        = signals.get("rsi", 50)
    sma20      = signals.get("sma20", close)
    sma50      = signals.get("sma50", close)
    atr        = signals.get("atr", 0.1)
    vol_ratio  = signals.get("vol_ratio", 1.0)
    candles    = signals.get("candle_count", 0)

    if candles < 50:
        return "hold", f"Insufficient data ({candles}/50)"

    # ── If in position: EXIT on trend break ──────────────────────────────
    if has_open_position and open_side == "buy":
        if entry_price is None:
            entry_price = close

        # Exit 1: Trend breaks (price below fast MA)
        if close < sma20:
            loss_pct = ((close - entry_price) / entry_price * 100)
            return "sell", f"TREND BREAK: Close below SMA20 ({loss_pct:+.1f}%)"

        # Exit 2: Overbought - take profits
        if rsi > 70:
            profit_pct = ((close - entry_price) / entry_price * 100)
            return "sell", f"OVERBOUGHT: RSI={rsi:.0f}, Profit +{profit_pct:.1f}%"

        # Exit 3: Strong move - take partial profits
        if close > (sma50 + 2*atr) and rsi > 55:
            profit_pct = ((close - entry_price) / entry_price * 100)
            return "sell", f"STRONG MOVE: +{profit_pct:.1f}% | RSI={rsi:.0f}"

        return "hold", f"Holding trending move | RSI={rsi:.0f}, Price vs SMA20: {close-sma20:+.0f}"

    # ── No position: ENTER on uptrend confirmation ──────────────────────
    if not has_open_position:
        
        # MUST HAVE: Uptrend (fast MA above slow MA)
        in_uptrend = sma20 > sma50
        
        # MUST HAVE: Price near fast MA (entry point)
        price_near_ma20 = abs(close - sma20) < atr
        
        # NICE TO HAVE: Volume
        volume_present = vol_ratio > 0.9
        
        # PRIMARY ENTRY: Textbook uptrend setup
        if (in_uptrend
                and close > sma20
                and close > sma50
                and 35 < rsi < 70
                and volume_present):
            
            target = close + (atr * 3)
            return "buy", (f"★ UPTREND ENTRY ★\n"
                           f"Price={close:.0f} > SMA20={sma20:.0f} > SMA50={sma50:.0f}\n"
                           f"RSI={rsi:.0f} | Vol={vol_ratio:.1f}x | Target={target:.0f}")

        # SECONDARY ENTRY: Price bounces off SMA20 in uptrend
        if (in_uptrend
                and price_near_ma20
                and close > sma50
                and 30 < rsi < 75
                and rsi > 35):  # Not too weak
            
            return "buy", (f"BOUNCE ENTRY\n"
                           f"Price bouncing off SMA20 in uptrend\n"
                           f"RSI={rsi:.0f}")

        # AVOID: Downtrend = no buys
        if sma20 < sma50:
            return "hold", f"DOWNTREND: SMA20 below SMA50 (NO BUYS)"

    return "hold", f"Wait | Price={close:.0f} vs SMA20={sma20:.0f}, RSI={rsi:.0f}"


def signal_strength(signals: dict) -> float:
    """Return 0-1 score for entry strength."""
    
    if not signals:
        return 0.0

    close     = signals.get("close", 0)
    rsi       = signals.get("rsi", 50)
    sma20     = signals.get("sma20", close)
    sma50     = signals.get("sma50", close)
    vol_ratio = signals.get("vol_ratio", 1.0)
    atr       = signals.get("atr", 0.1)

    # Uptrend check
    in_uptrend = 1.0 if sma20 > sma50 else 0.0

    # Price position relative to MAs
    if close >= sma20:
        price_score = 1.0
    elif close > sma50:
        price_score = 0.5
    else:
        price_score = 0.0

    # RSI (sweet spot 45-60)
    if 45 <= rsi <= 60:
        rsi_score = 1.0
    elif 35 <= rsi <= 70:
        rsi_score = 0.5
    else:
        rsi_score = 0.0

    # Volume
    vol_score = min(1.0, vol_ratio / 1.5)

    # Composite
    score = (in_uptrend * 0.40) + (price_score * 0.35) + (rsi_score * 0.15) + (vol_score * 0.10)
    
    return round(min(1.0, max(0.0, score)), 3)
