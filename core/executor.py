# core/executor.py — Order execution manager
#
# Currently a thin wrapper around exchange.place_order().
# This is where you'll add more sophisticated order logic later:
#   - Limit orders with timeout fallback to market
#   - Partial fill detection and handling
#   - Retry logic on transient network errors
#   - Slippage tracking (expected fill vs actual fill)
#
# For now it handles the paper/live split cleanly and logs everything.

from core.exchange import place_order, get_current_price
from config import TRADING_MODE, TAKER_FEE, MAKER_FEE


class ExecutionResult:
    """Structured result from an order execution attempt."""

    def __init__(self, success: bool, order_id: str, fill_price: float,
                 quantity: float, fee_inr: float, mode: str, error: str = ""):
        self.success     = success
        self.order_id    = order_id
        self.fill_price  = fill_price
        self.quantity    = quantity
        self.fee_inr     = fee_inr
        self.mode        = mode        # 'paper' or 'live'
        self.error       = error

    def __repr__(self):
        if self.success:
            return (f"<ExecutionResult {self.mode.upper()} "
                    f"filled={self.quantity:.6f} @ ₹{self.fill_price:.2f} "
                    f"fee=₹{self.fee_inr:.4f}>")
        return f"<ExecutionResult FAILED: {self.error}>"


class Executor:
    """
    Handles order placement with basic error handling and slippage tracking.
    One instance lives for the bot's lifetime.
    """

    def __init__(self):
        self.total_fees_paid = 0.0    # running total of fees across all trades
        self.total_slippage  = 0.0    # difference between expected and actual fills
        print(f"[Executor] Initialised in {TRADING_MODE.upper()} mode.")

    def execute(self, symbol: str, side: str,
                quantity: float, expected_price: float) -> ExecutionResult:
        """
        Place a market order and return a structured ExecutionResult.

        Args:
            symbol:         e.g. "BTC/INR"
            side:           "buy" or "sell"
            quantity:       amount of base asset (e.g. BTC)
            expected_price: price we saw when generating the signal (for slippage calc)

        Returns:
            ExecutionResult — always returns one, never raises
        """
        try:
            order = place_order(symbol, side, quantity, order_type="market")

            fill_price = order["price"]
            fee_inr    = order["fee"]

            # Track slippage (expected vs actual fill)
            slippage = abs(fill_price - expected_price) / expected_price
            self.total_slippage  += slippage
            self.total_fees_paid += fee_inr

            if slippage > 0.005:   # >0.5% slippage is worth logging
                print(f"[Executor] ⚠️  High slippage: {slippage*100:.3f}% "
                      f"(expected ₹{expected_price:.2f}, got ₹{fill_price:.2f})")

            return ExecutionResult(
                success     = True,
                order_id    = order["id"],
                fill_price  = fill_price,
                quantity    = quantity,
                fee_inr     = fee_inr,
                mode        = order["mode"],
            )

        except Exception as e:
            print(f"[Executor] Order failed: {e}")
            return ExecutionResult(
                success     = False,
                order_id    = "",
                fill_price  = expected_price,
                quantity    = quantity,
                fee_inr     = 0.0,
                mode        = TRADING_MODE,
                error       = str(e),
            )

    def stats(self) -> str:
        """Return a summary of execution quality."""
        avg_slippage = self.total_slippage   # cumulative, divide by trade count externally
        return (f"Total fees paid: ₹{self.total_fees_paid:.4f} | "
                f"Cumulative slippage: {avg_slippage*100:.4f}%")
