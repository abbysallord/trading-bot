#!/usr/bin/env python3
# main.py — Trading bot entry point

import asyncio
import signal
import sys
from datetime import datetime

from config import (
    SYMBOLS, TIMEFRAME, STARTING_CAPITAL, MIN_CANDLES
)
from config import TRADING_MODE as _TM
TRADING_MODE = _TM.lower()

from core.database   import init_db, get_recent_candles, open_trade, close_trade
from core.exchange   import fetch_historical_candles, live_candle_feed, place_order, get_current_price
from core.indicators import compute_indicators, get_latest_signals, describe_market_state
from core.strategy_hybrid import generate_signal, signal_strength
from core.risk       import RiskManager
from core.alerts     import (alert_startup, alert_trade_opened,
                              alert_trade_closed, alert_risk_halt)

# ── Global state ─────────────────────────────────────────────────────────────
risk    = RiskManager(starting_capital=STARTING_CAPITAL)
running = True   # set to False on SIGINT/SIGTERM for graceful shutdown


# ── Graceful shutdown ────────────────────────────────────────────────────────
def handle_shutdown(sig, frame):
    global running
    print("\n[Main] Shutdown signal received. Stopping bot gracefully...")
    running = False
    sys.exit(0)

signal.signal(signal.SIGINT,  handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# ── Core callback: called on every new closed candle ────────────────────────
def on_new_candle(candle: dict) -> None:
    current_price = candle["close"]
    now           = candle["datetime"]
    sym           = candle.get("symbol", SYMBOLS[0])

    # ── 1. Load recent candles + compute indicators ──────────────────────────
    df = get_recent_candles(sym, limit=200)
    if df.empty:
        print(f"[Main] No candle data in DB yet for {sym} — waiting...")
        return

    df      = compute_indicators(df)
    signals = get_latest_signals(df)

    if not signals:
        print(f"[Main] {now} | {sym} | Insufficient data for indicators")
        return

    # ── 2. Print status every candle ────────────────────────────────────────
    print(f"\n[{now}] {sym} | {describe_market_state(signals)}")
    print(f"         {risk.status()}")

    # ── 3. If position is open — check exit conditions ──────────────────────
    if risk.open_position:
        # Check if the open position belongs to the CURRENT symbol being processed
        if risk.open_position.get("symbol") == sym:
            should_exit, exit_reason = risk.check_exit_conditions(current_price)

            # Also check strategy signal for early exit
            sig, sig_reason = generate_signal(
                signals,
                has_open_position = True,
                open_side         = risk.open_position["side"]
            )
            if sig == "sell" and exit_reason == "hold":
                should_exit = True
                exit_reason = "signal"

            if should_exit:
                _close_position(sym, current_price, exit_reason, signals)
        return   # don't look for new entries while in ANY trade (MAX_CONCURRENT=1)

    # ── 4. No position open — look for entry signal ──────────────────────────
    sig, sig_reason = generate_signal(signals, has_open_position=False)
    strength        = signal_strength(signals)

    print(f"         Signal: {sig.upper()} | Strength: {strength:.2f} | {sig_reason}")

    if sig == "buy":
        # ── LLM Sentiment Filter ─────────────────────────────────────────────
        print(f"         [LLM] Buy signal spotted for {sym}. Fetching latest news to pass to Mistral AI...")
        from core.news_fetcher import get_latest_crypto_headlines
        from core.llm_filter import get_market_sentiment
        
        headlines = get_latest_crypto_headlines(10)
        sentiment = get_market_sentiment(headlines)
        
        print(f"         [LLM] Mistral Sentiment: {sentiment}")
        
        if sentiment == "BEARISH":
            print("         ⛔ LLM Override: News is BAD. Cancelling trade.")
            return

        # Gate through risk manager
        allowed, risk_reason = risk.check_trade(sig, current_price)

        if not allowed:
            print(f"         ⛔ Risk gate blocked: {risk_reason}")
            return

        _open_position(sym, sig, current_price, signals, sig_reason)


def _open_position(sym: str, side: str, price: float, signals: dict, reason: str) -> None:
    position_inr, quantity = risk.calculate_position_size(price)
    stop_loss              = risk.calculate_stop_loss(price, side)
    take_profit            = risk.calculate_take_profit(price, side)

    # Place order (paper or live)
    order = place_order(sym, side, quantity)
    fill_price = order["price"]
    fee        = order["fee"]

    # Record in DB
    trade_id = open_trade(
        symbol         = sym,
        mode           = TRADING_MODE,
        side           = side,
        entry_price    = fill_price,
        quantity       = quantity,
        position_value = position_inr,
        stop_loss      = stop_loss,
        take_profit    = take_profit,
        rsi            = signals.get("rsi"),
        bb_pct         = signals.get("bb_pct"),
    )

    # Update risk state
    risk.on_trade_opened(
        trade_id       = trade_id,
        side           = side,
        entry_price    = fill_price,
        quantity       = quantity,
        position_value = position_inr,
        stop_loss      = stop_loss,
        take_profit    = take_profit,
    )
    # Tag the open position with the symbol!
    risk.open_position["symbol"] = sym

    # Alert
    alert_trade_opened(
        side           = side,
        price          = fill_price,
        quantity       = quantity,
        position_value = position_inr,
        stop_loss      = stop_loss,
        take_profit    = take_profit,
        reason         = reason,
    )


def _close_position(sym: str, price: float, exit_reason: str, signals: dict) -> None:
    """Close the current position and record PnL."""
    pos       = risk.open_position
    trade_id  = pos["trade_id"]
    quantity  = pos["quantity"]
    side      = pos["side"]

    # Place closing order
    close_side = "sell" if side == "buy" else "buy"
    order      = place_order(sym, close_side, quantity)
    fill_price = order["price"]
    fee        = order["fee"]

    # Compute net PnL
    if side == "buy":
        gross_pnl = (fill_price - pos["entry_price"]) * quantity
    else:
        gross_pnl = (pos["entry_price"] - fill_price) * quantity

    total_fees = (pos["entry_price"] * quantity * 0.001) + fee   # entry fee + exit fee
    net_pnl    = gross_pnl - total_fees

    # Update DB
    close_trade(trade_id, fill_price, exit_reason, total_fees)

    # Update risk manager
    risk.on_trade_closed(fill_price, net_pnl)

    # Alert
    alert_trade_closed(
        side              = side,
        entry_price       = pos["entry_price"],
        exit_price        = fill_price,
        net_pnl           = net_pnl,
        exit_reason       = exit_reason,
        capital_remaining = risk.current_capital,
    )

    # Check if drawdown or daily loss halt is now triggered
    _, risk_reason = risk.check_trade("buy", fill_price)
    if "halt" in risk_reason.lower() or "limit hit" in risk_reason.lower() or "breached" in risk_reason.lower():
        print(f"\n🚨 [Main] RISK HALT: {risk_reason}")
        alert_risk_halt(risk_reason, risk.current_capital)


# ── Startup ──────────────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print(f"  CoinDCX Trading Bot")
    print(f"  Mode:    {TRADING_MODE.upper()}")
    print(f"  Symbols: {', '.join(SYMBOLS)}")
    print(f"  Capital: ₹{STARTING_CAPITAL:.2f}")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if TRADING_MODE == "live":
        print("\n⚠️  WARNING: LIVE mode is active. Real orders will be placed.")
        print("   Press Ctrl+C within 5 seconds to abort.\n")
        await asyncio.sleep(5)
        
        from core.exchange import get_account_balance
        try:
            balances = get_account_balance()
            actual_inr = balances.get("INR", 0.0)
            print(f"[Main] Live Mode Enabled. Fetching real balance: ₹{actual_inr:.2f}")
            if actual_inr > 0:
                global risk
                risk.starting_capital = actual_inr
                risk.current_capital  = actual_inr
                risk.peak_capital     = actual_inr
                print(f"[Main] Risk Manager synced to live capital: ₹{actual_inr:.2f}")
            else:
                print(f"[Main] ⚠️ Live balance is zero or fetch failed. Check credentials!")
        except Exception as e:
            print(f"[Main] Error fetching live account balance: {e}")

    # Initialise database
    init_db()

    # Fetch historical candles for indicator warm-up
    print(f"\n[Main] Fetching historical data for warm-up...")
    for sym in SYMBOLS:
        fetch_historical_candles(sym, TIMEFRAME, limit=100)

    # Check we have enough candles
    from core.database import get_candle_count
    for sym in SYMBOLS:
        count = get_candle_count(sym)
        if count < MIN_CANDLES:
            print(f"[Main] Only {count} candles available for {sym}. Need {MIN_CANDLES}.")
        else:
            print(f"[Main] {count} candles loaded for {sym}. Indicators ready.")

    # Send startup alert
    alert_startup(TRADING_MODE, ", ".join(SYMBOLS), STARTING_CAPITAL)

    # Start live feed
    print(f"\n[Main] Starting live candle feed...\n")
    await live_candle_feed(
        symbols       = SYMBOLS,
        timeframe     = TIMEFRAME,
        on_candle     = on_new_candle,
        poll_interval = 20,
    )

if __name__ == "__main__":
    asyncio.run(main())
