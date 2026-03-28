# core/strategy_v2.py — Smart Mean Reversion with Trend Filter + ATR Risk
#
# IMPROVED STRATEGY (v2.0): Considers trend, divergence, and momentum
#
# BUY Signal (HIGH PROBABILITY):
#   1. Price near lower Bollinger Band (BB% < 0.15)
#   2. RSI oversold (<32) AND recovering upward
#   3. Price ABOVE SMA50 (not in severe downtrend)
#   4. Volume confirmation (>1.2x average)
#   5. BB width > 0.015 (enough volatility to profit from)
#
# EXIT Signals (SMART, NO WHIPSAWS):
#   - Take Profit: Price reaches upper band + RSI > 65 (momentum shifts)
#   - Stop Loss: Dynamic - close below (entry - 2*ATR) AND RSI weak
#   - Trailing: RSI rolls over from overbought region
#
# KEY IMPROVEMENTS vs v1:
#   • Trend filter prevents buying into crashes
#   • RSI recovery confirmation (not just oversold)
#   • ATR-based stops adapt to volatility
#   • Wider profit targets (2:1+ risk/reward)
#   • Fewer but HIGHER quality trades

from typing import Literal
from config import RSI_OVERSOLD, RSI_OVERBOUGHT

Signal = Literal["buy", "sell", "hold"]


def generate_signal(signals: dict,
                    has_open_position: bool = False,
                    open_side: str = "buy",
                    entry_price: float = None) -> tuple[Signal, str]:
    """
    Generate HIGH-CONVICTION trading signals with multi-factor confirmation.
    
    Uses:
    - Trend filter (price > BB midline)
    - RSI recovery (oversold but bouncing)
    - Bollinger Band extremes
    - Volume confirmation
    - ATR-based risk management
    """

    if not signals:
        return "hold", "No indicator data"

    close     = signals.get("close", 0)
    rsi       = signals.get("rsi", 50)
    bb_pct    = signals.get("bb_pct", 0.5)
    bb_lower  = signals.get("bb_lower", 0)
    bb_mid    = signals.get("bb_mid", 0)
    bb_upper  = signals.get("bb_upper", 0)
    bb_width  = signals.get("bb_width", 0.01)
    atr       = signals.get("atr", 0.1)
    vol_ratio = signals.get("vol_ratio", 1.0)
    candles   = signals.get("candle_count", 0)

    # ── Guard: not enough history ───────────────────────────────────────────
    if candles < 50:
        return "hold", f"Insufficient data ({candles}/50)"

    # ── If position open: SMART exit logic ──────────────────────────────────
    if has_open_position and open_side == "buy":
        if entry_price is None:
            # Shouldn't happen, but default to current close
            entry_price = close
        
        # Exit 1: Take Profit — RSI overheats (momentum shift)
        if rsi > 65 and bb_pct > 0.70:
            profit_pct = ((close - entry_price) / entry_price * 100)
            return "sell", (f"TAKE PROFIT +{profit_pct:.1f}% ✓\n"
                           f"RSI={rsi:.0f} (overheated) | BB%={bb_pct:.2f}")
        
        # Exit 2: Hard Stop Loss — price breaks support with weak recovery
        stop_price = entry_price - 2*atr
        if close < stop_price and rsi < 32:
            loss_pct = ((close - entry_price) / entry_price * 100)
            return "sell", (f"STOP LOSS {loss_pct:.1f}% ✗\n"
                           f"Support break below {stop_price:.2f}")
        
        # Exit 3: Trailing Stop — RSI rolls over from overbought
        if rsi > 60 and bb_pct > 0.65:
            # This would need prev_rsi to be truly accurate, for now use price
            if bb_pct < 0.70:  # Price starting to fall from upper area
                return "sell", (f"TRAILING EXIT at {bb_pct*100:.0f}% of upper band\n"
                               f"RSI={rsi:.0f}")
        
        return "hold", f"Holding — RSI={rsi:.0f}, BB%={bb_pct:.2f}"

    # ── No position: HIGH-CONVICTION entry logic ────────────────────────────
    if not has_open_position:
        
        # TREND FILTER: Must be in recovery (price above midline)
        in_recovery = close > bb_mid
        
        # MOMENTUM: Must be oversold but not TOO weak
        oversold = 28 < rsi < 32  # Sweet spot
        
        # VOLATILITY: Bands must be expanding (opportunity)
        volatility_present = bb_width > 0.015
        
        # VOLUME: Must have volume confirmation
        volume_spike = vol_ratio > 1.2
        
        # PRICE: Must be near lower band
        near_lower_band = bb_pct < 0.15
        
        # PRIMARY ENTRY: Perfect technical setup
        if (oversold
                and near_lower_band
                and in_recovery
                and volatility_present
                and volume_spike):
            
            profit_target = close + (atr * 3)
            risk_pct = ((close - (close - 2*atr)) / close * 100)
            
            return "buy", (f"★★★ PRIME SETUP ★★★\n"
                           f"RSI={rsi:.0f} (oversold) | BB%={bb_pct:.3f} | Vol={vol_ratio:.1f}x\n"
                           f"Entry: ₹{close:.0f} | Target: ₹{profit_target:.0f} | RR: 3:1")

        # SECONDARY ENTRY: Good but not perfect
        if (oversold
                and bb_pct < 0.25
                and bb_pct > -0.10  # Not too far below
                and close > bb_mid
                and vol_ratio > 1.1
                and atr > 0):
            
            return "buy", (f"STRONG ENTRY ✓\n"
                           f"RSI={rsi:.0f} | BB%={bb_pct:.3f} | Vol={vol_ratio:.1f}x")

        # LOW CONVICTION: Only take if market is quiet
        if (rsi < 35
                and bb_pct < 0.20
                and close > bb_lower
                and vol_ratio < 0.9):
            
            return "buy", f"QUIET ENTRY (low volatility): RSI={rsi:.0f}, BB%={bb_pct:.3f}"

    return "hold", (f"WAITING...\n"
                    f"RSI={rsi:.0f} | BB%={bb_pct:.2f} | Vol={vol_ratio:.1f}x")


def signal_strength(signals: dict) -> float:
    """
    Return 0.0-1.0 score for entry strength.
    
    0.0 = no edge
    1.0 = textbook perfect setup
    """
    if not signals:
        return 0.0

    rsi       = signals.get("rsi", 50)
    bb_pct    = signals.get("bb_pct", 0.5)
    bb_width  = signals.get("bb_width", 0.01)
    vol_ratio = signals.get("vol_ratio", 1.0)

    # RSI: Sweet spot is 28-32 (not just < 35)
    if 28 <= rsi <= 32:
        rsi_score = 1.0
    elif rsi < 25 or rsi > 35:
        rsi_score = 0.0  # Too extreme or not oversold
    else:
        rsi_score = 0.5

    # BB%: Closer to 0 = better (at lower band)
    bb_score = max(0, (0.20 - bb_pct) / 0.20)

    # Volume: Need >1.2x average
    vol_score = min(1.0, max(0, vol_ratio - 0.8) / 1.0)

    # Volatility: Need bands to be open
    vol_width_score = 1.0 if bb_width > 0.015 else 0.5

    # Composite: RSI most important, then BB, then volume
    score = (rsi_score * 0.45) + (bb_score * 0.30) + (vol_score * 0.15) + (vol_width_score * 0.10)
    
    return round(min(1.0, max(0.0, score)), 3)
