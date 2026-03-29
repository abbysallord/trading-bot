# core/strategy_hybrid.py — Asymmetric Trend-Rider Strategy
#
# A fundamentally power-law aligned strategy that:
# 1. Enters when Momentum (EMA 9 > EMA 21) aligns with Macro Trend (SMA 50).
# 2. Removes Take-Profits completely to capture 50-100% runners.
# 3. Exits based on ATR mathematical trailing stops or a complete momentum break.

from typing import Literal
from config import EMA_FAST, EMA_SLOW, SMA_TREND

Signal = Literal["buy", "sell", "hold"]

def generate_signal(signals: dict,
                    has_open_position: bool = False,
                    open_side: str = "buy",
                    entry_price: float = None) -> tuple[Signal, str]:
    if not signals:
        return "hold", "No data"

    close      = signals.get("close", 0)
    ema_fast   = signals.get("ema_fast", close)
    ema_slow   = signals.get("ema_slow", close)
    sma_trend  = signals.get("sma_trend", close)
    vol_ratio  = signals.get("vol_ratio", 1.0)
    candles    = signals.get("candle_count", 0)

    if candles < 50:
        return "hold", f"Insufficient data ({candles}/50)"

    # ── OPEN POSITION EXIT LOGIC ─────────────────────────────────────────────
    if has_open_position and open_side == "buy":
        # Exit 1: Total momentum failure (Fast EMA crosses below Slow EMA + Price falls below Fast EMA)
        if close < ema_fast and ema_fast < ema_slow:
            return "sell", f"MOMENTUM BREAK: Price {close:.2f} closed below Fast EMA."

        # Exit 2: Hard macroeconomic trend break
        if close < sma_trend:
            return "sell", f"TREND BREAK: Price {close:.2f} fell below SMA 50."

        return "hold", f"Riding Trend | P: {close:.2f} | EMA9: {ema_fast:.2f}"

    # ── NO POSITION ENTRY LOGIC ──────────────────────────────────────────────
    if not has_open_position:
        
        # Condition 1: Fast Momentum > Slow Momentum
        momentum_bullish = ema_fast > ema_slow
        
        # Condition 2: Price > Macro Trend
        trend_bullish = close > sma_trend
        
        # Condition 3: Expanding Volume validates the move
        volume_bullish = vol_ratio >= 1.0

        if momentum_bullish and trend_bullish and volume_bullish:
            return "buy", (f"★ TREND BREAKOUT ★\n"
                           f"EMA{EMA_FAST} > EMA{EMA_SLOW} | Close > SMA{SMA_TREND} | Vol={vol_ratio:.1f}x")

        return "hold", f"Wait | Trend: {'UP' if trend_bullish else 'DOWN'} | Mom: {'UP' if momentum_bullish else 'DOWN'} | Vol={vol_ratio:.1f}x"


def signal_strength(signals: dict) -> float:
    """Return 0-1 score for entry setup quality."""
    
    if not signals:
        return 0.0

    close      = signals.get("close", 0)
    ema_fast   = signals.get("ema_fast", close)
    ema_slow   = signals.get("ema_slow", close)
    sma_trend  = signals.get("sma_trend", close)
    vol_ratio  = signals.get("vol_ratio", 1.0)

    # Trend filter
    if close < sma_trend or ema_fast < ema_slow:
        return 0.0

    # How strong is the momentum gap?
    momentum_gap = (ema_fast - ema_slow) / ema_slow
    mom_score = min(1.0, momentum_gap * 100) # Max score if EMA gap is > 1%

    # Volume confirmation
    vol_score = min(1.0, vol_ratio / 2.0)

    strength = (mom_score * 0.6) + (vol_score * 0.4)
    return round(strength, 3)
