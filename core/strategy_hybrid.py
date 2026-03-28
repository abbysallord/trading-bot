# core/strategy_hybrid.py — Flexible Hybrid Strategy
#
# Combines BOTH momentum (uptrend) and mean reversion (oversold bounce)
# This works in BOTH trending AND choppy markets
#
# ENTRY SIGNALS:
#   1. MOMENTUM: Price > SMA20, SMA20 > SMA50, RSI 35-70 (uptrend trades)
#   2. MEAN REVERSION: RSI < 40, BB% < 0.25, Volume > 1.0x (oversold bounce)
#   3. COMBO: Uptrend + Price near SMA20 (lowest-risk entry)
#
# EXIT SIGNALS:
#   - Downtrend: Price < SMA20
#   - Overbought: RSI > 70
#   - Strong move: Price > SMA50 + 2*ATR
#   - Stop loss: Entry price - 2*ATR

from typing import Literal

Signal = Literal["buy", "sell", "hold"]


def generate_signal(signals: dict,
                    has_open_position: bool = False,
                    open_side: str = "buy",
                    entry_price: float = None) -> tuple[Signal, str]:
    """
    Hybrid strategy: momentum + mean reversion.
    Works in both trending and choppy markets.
    """

    if not signals:
        return "hold", "No data"

    close      = signals.get("close", 0)
    rsi        = signals.get("rsi", 50)
    sma20      = signals.get("sma20", close)
    sma50      = signals.get("sma50", close)
    atr        = signals.get("atr", 0.1)
    vol_ratio  = signals.get("vol_ratio", 1.0)
    bb_pct     = signals.get("bb_pct", 0.5)
    bb_lower   = signals.get("bb_lower", close - atr)
    bb_upper   = signals.get("bb_upper", close + atr)
    bb_width   = signals.get("bb_width", 0.1)
    candles    = signals.get("candle_count", 0)

    if candles < 50:
        return "hold", f"Insufficient data ({candles}/50)"

    # ── If in position: EXIT ────────────────────────────────────────────────
    if has_open_position and open_side == "buy":
        if entry_price is None:
            entry_price = close

        # Exit 1: Mean Reversion Target Reached (Upper Band or Overbought)
        if close > bb_upper or rsi > 70:
            profit_pct = ((close - entry_price) / entry_price * 100)
            return "sell", f"TARGET REACHED: RSI={rsi:.0f}, BB={bb_pct:.2f} ({profit_pct:+.1f}%)"

        # Exit 2: Return to mean (Mid Band) if momentum stalls
        if close > sma20 and rsi > 55:
             profit_pct = ((close - entry_price) / entry_price * 100)
             return "sell", f"RETURN TO MEAN: SMA20 reached ({profit_pct:+.1f}%)"

        # Exit 3: Hard Stop Loss (Falling Knife protection)
        if close < (entry_price - 2.5 * atr):
             loss_pct = ((close - entry_price) / entry_price * 100)
             return "sell", f"HARD STOP: Loss {loss_pct:.1f}%"

        return "hold", f"Holding Mean Reversion | Price {close:.0f}, RSI {rsi:.0f}"

    # ── No position: ENTER ──────────────────────────────────────────────────
    if not has_open_position:
        
        # ENTRY 1: EXTREME OVERSOLD CLIMAX
        # Price dumped outside lower band, RSI is crushed, high volume
        if (close < bb_lower
                and rsi < 32 
                and vol_ratio > 1.2):
            
            return "buy", (f"★ CLIMAX REVERSAL ★\n"
                           f"BB%={bb_pct:.2f} | RSI={rsi:.0f} | Vol={vol_ratio:.1f}x")

        # ENTRY 2: DOUBLE BOTTOM / QUIET ACCUMULATION
        # RSI oversold, price resting on lower band, low volatility
        if (bb_pct < 0.10
                and rsi < 35
                and bb_width < 0.05):
            
            return "buy", (f"QUIET ACCUMULATION\n"
                           f"BB%={bb_pct:.2f} | RSI={rsi:.0f}")

        return "hold", f"Wait | BB%={bb_pct:.2f}, RSI={rsi:.0f}, Vol={vol_ratio:.1f}x"


def signal_strength(signals: dict) -> float:
    """Return 0-1 score for entry setup quality."""
    
    if not signals:
        return 0.0

    close     = signals.get("close", 0)
    rsi       = signals.get("rsi", 50)
    sma20     = signals.get("sma20", close)
    sma50     = signals.get("sma50", close)
    vol_ratio = signals.get("vol_ratio", 1.0)
    bb_pct    = signals.get("bb_pct", 0.5)

    # Trend check
    in_uptrend = 1.0 if sma20 > sma50 else 0.0

    # Momentum setup score
    if close > sma20 > sma50:
        momentum_score = 1.0
    elif close > sma20:
        momentum_score = 0.7
    else:
        momentum_score = 0.0

    # Oversold setup score
    if rsi < 35:
        oversold_score = 1.0
    elif rsi < 40:
        oversold_score = 0.7
    else:
        oversold_score = 0.0

    # RSI sweet spot (45-55 is best for entries)
    if 45 <= rsi <= 55:
        rsi_score = 1.0
    elif 35 <= rsi <= 70:
        rsi_score = 0.6
    else:
        rsi_score = 0.0

    # Volume confirmation
    vol_score = min(1.0, vol_ratio / 1.5)

    # Pick the BETTER of momentum vs mean reversion signals
    momentum_strength = (in_uptrend * 0.4) + (momentum_score * 0.3) + (rsi_score * 0.2) + (vol_score * 0.1)
    reversion_strength = (oversold_score * 0.4) + ((1.0 - bb_pct) * 0.3) + (vol_score * 0.3)
    
    return round(max(min(1.0, momentum_strength), min(1.0, reversion_strength)), 3)
