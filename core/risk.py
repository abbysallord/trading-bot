# core/risk.py — Hard risk guardrails
#
# This module is the gatekeeper between signal generation and order execution.
# Every trade must pass through RiskManager.check_trade() before it's placed.
#
# Design principle: this module uses ONLY deterministic logic.
# No ML, no LLM, no probability — hard numeric limits only.
# When in doubt, the answer is "don't trade."

import time
from datetime import date
from typing import Tuple, Optional
from config import (
    STARTING_CAPITAL, MAX_POSITION_SIZE, MAX_CONCURRENT,
    DAILY_LOSS_LIMIT, MAX_DRAWDOWN_PCT, STOP_LOSS_PCT,
    TAKE_PROFIT_PCT, MAX_TRADES_PER_DAY, COOLDOWN_SECONDS,
    ROUND_TRIP_FEE, TAKER_FEE
)
from core.database import get_daily_pnl, get_trade_count_today


class RiskManager:
    """
    Stateful risk manager. One instance lives for the bot's lifetime.

    Tracks:
      - Peak capital (for drawdown calculation)
      - Current open position (only 1 allowed)
      - Last trade timestamp (for cooldown enforcement)
      - Daily trade count and PnL
    """

    def __init__(self, starting_capital: float = STARTING_CAPITAL):
        self.starting_capital  = starting_capital
        self.current_capital   = starting_capital
        self.peak_capital      = starting_capital

        self.open_position: Optional[dict] = None   # None = flat
        self.last_trade_time: float        = 0.0    # Unix timestamp
        self.last_was_loss: bool           = False

        print(f"[Risk] Initialised. Capital: ₹{starting_capital:.2f}")
        print(f"[Risk] Max position: ₹{MAX_POSITION_SIZE:.2f} | "
              f"Daily loss limit: ₹{DAILY_LOSS_LIMIT:.2f} | "
              f"Max drawdown: {MAX_DRAWDOWN_PCT*100:.0f}%")

    # ── Capital tracking ────────────────────────────────────────────────────

    def update_capital(self, new_capital: float) -> None:
        """Call after each trade closes to update capital and peak."""
        self.current_capital = new_capital
        if new_capital > self.peak_capital:
            self.peak_capital = new_capital

    def get_drawdown(self) -> float:
        """Current drawdown from peak capital as a fraction (0.0 – 1.0)."""
        if self.peak_capital <= 0:
            return 0.0
        return (self.peak_capital - self.current_capital) / self.peak_capital

    # ── Position sizing ─────────────────────────────────────────────────────

    def calculate_position_size(self, price: float) -> Tuple[float, float]:
        """
        Return (position_value_inr, quantity) for a trade.

        Position value is capped at MAX_POSITION_SIZE and also
        capped at available capital minus a 10% buffer.

        Returns (0, 0) if we can't afford a meaningful trade.
        """
        available     = self.current_capital * 0.90   # keep 10% buffer
        position_inr  = min(MAX_POSITION_SIZE, available)

        # Minimum viable position: must profit more than fees after round-trip
        # Min profit needed = position * round_trip_fee
        # At 1.5% stop-loss and 0.7% take-profit, minimum position ≈ ₹30
        if position_inr < 30:
            return 0.0, 0.0

        quantity = position_inr / price
        return round(position_inr, 2), round(quantity, 8)

    def calculate_stop_loss(self, entry_price: float, side: str = "buy") -> float:
        """Compute the stop-loss price for a given entry."""
        if side == "buy":
            return round(entry_price * (1 - STOP_LOSS_PCT), 2)
        else:
            return round(entry_price * (1 + STOP_LOSS_PCT), 2)

    def calculate_take_profit(self, entry_price: float, side: str = "buy") -> float:
        """Compute the take-profit price for a given entry."""
        if side == "buy":
            return round(entry_price * (1 + TAKE_PROFIT_PCT), 2)
        else:
            return round(entry_price * (1 - TAKE_PROFIT_PCT), 2)

    # ── Pre-trade gate ──────────────────────────────────────────────────────

    def check_trade(self, signal: str, current_price: float) -> Tuple[bool, str]:
        """
        Run all risk checks before allowing a trade.

        Returns (allowed: bool, reason: str)
        allowed=True  → trade can proceed
        allowed=False → reason explains why it was blocked
        """

        # 1. Signal must be actionable
        if signal not in ("buy", "sell"):
            return False, f"No actionable signal (got '{signal}')"

        # 2. Only one open position at a time
        if self.open_position is not None:
            return False, "Position already open — cannot open another"

        # 3. Check daily loss limit (query DB for today's PnL)
        daily_pnl = get_daily_pnl()
        if daily_pnl <= -DAILY_LOSS_LIMIT:
            return False, (f"Daily loss limit hit (₹{daily_pnl:.2f} of "
                           f"-₹{DAILY_LOSS_LIMIT:.2f} limit) — bot halted for today")

        # 4. Check max drawdown
        drawdown = self.get_drawdown()
        if drawdown >= MAX_DRAWDOWN_PCT:
            return False, (f"Max drawdown breached ({drawdown*100:.1f}% of "
                           f"{MAX_DRAWDOWN_PCT*100:.0f}% limit) — bot stopped")

        # 5. Check daily trade count
        trades_today = get_trade_count_today()
        if trades_today >= MAX_TRADES_PER_DAY:
            return False, (f"Daily trade limit reached ({trades_today} trades)")

        # 6. Cooldown after a loss
        if self.last_was_loss:
            elapsed = time.time() - self.last_trade_time
            if elapsed < COOLDOWN_SECONDS:
                remaining = int(COOLDOWN_SECONDS - elapsed)
                return False, f"Cooldown active after loss — {remaining}s remaining"

        # 7. Position size check
        position_inr, quantity = self.calculate_position_size(current_price)
        if position_inr <= 0:
            return False, f"Insufficient capital for a viable trade (₹{self.current_capital:.2f})"

        # 8. Profit sanity: take-profit must exceed round-trip fees
        tp_gain_pct = TAKE_PROFIT_PCT
        if tp_gain_pct <= ROUND_TRIP_FEE:
            return False, (f"Take-profit ({tp_gain_pct*100:.2f}%) doesn't exceed "
                           f"round-trip fees ({ROUND_TRIP_FEE*100:.2f}%)")

        return True, "All checks passed"

    # ── Post-trade updates ──────────────────────────────────────────────────

    def on_trade_opened(self, trade_id: int, side: str, entry_price: float,
                        quantity: float, position_value: float,
                        stop_loss: float, take_profit: float) -> None:
        """Call immediately after a trade is opened."""
        self.open_position = {
            "trade_id":      trade_id,
            "side":          side,
            "entry_price":   entry_price,
            "quantity":      quantity,
            "position_value": position_value,
            "stop_loss":     stop_loss,
            "take_profit":   take_profit,
        }
        self.last_trade_time = time.time()
        print(f"[Risk] Position opened: {side.upper()} ₹{position_value:.2f} "
              f"@ ₹{entry_price:.2f}  SL=₹{stop_loss:.2f}  TP=₹{take_profit:.2f}")

    def on_trade_closed(self, exit_price: float, net_pnl: float) -> None:
        """Call immediately after a trade is closed."""
        self.last_was_loss   = net_pnl < 0
        self.last_trade_time = time.time()
        self.update_capital(self.current_capital + net_pnl)
        self.open_position   = None

        emoji = "✅" if net_pnl >= 0 else "❌"
        print(f"[Risk] Position closed @ ₹{exit_price:.2f}  "
              f"Net PnL: ₹{net_pnl:+.4f}  {emoji}  "
              f"Capital: ₹{self.current_capital:.2f}")

    # ── Stop-loss / take-profit check ───────────────────────────────────────

    def check_exit_conditions(self, current_price: float) -> Tuple[bool, str]:
        """
        Check if the current open position should be closed.
        Call this on every new candle while a position is open.

        Returns (should_exit: bool, reason: str)
        """
        pos = self.open_position
        if pos is None:
            return False, "No open position"

        if pos["side"] == "buy":
            if current_price <= pos["stop_loss"]:
                return True, "sl"
            if current_price >= pos["take_profit"]:
                return True, "tp"
        else:
            if current_price >= pos["stop_loss"]:
                return True, "sl"
            if current_price <= pos["take_profit"]:
                return True, "tp"

        return False, "hold"

    # ── Status summary ──────────────────────────────────────────────────────

    def status(self) -> str:
        """Return a one-line status string for logging."""
        daily_pnl    = get_daily_pnl()
        trades_today = get_trade_count_today()
        drawdown     = self.get_drawdown()
        position_str = (f"OPEN {self.open_position['side'].upper()} "
                        f"@ ₹{self.open_position['entry_price']:.2f}"
                        if self.open_position else "FLAT")

        return (f"Capital: ₹{self.current_capital:.2f} | "
                f"Drawdown: {drawdown*100:.1f}% | "
                f"Daily PnL: ₹{daily_pnl:+.2f} | "
                f"Trades today: {trades_today}/{MAX_TRADES_PER_DAY} | "
                f"Position: {position_str}")
