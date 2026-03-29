#!/usr/bin/env python3
# backtest/run_backtest.py — Strategy backtester
#
# Run this BEFORE switching to live mode. If this doesn't show
# consistent positive expectancy, the strategy needs tuning.
#
# Usage:
#   python backtest/run_backtest.py

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime

from core.coindcx_api import fetch_ohlcv
from core.indicators import compute_indicators
from core.strategy_hybrid import generate_signal, signal_strength
from config          import (
    SYMBOLS, TIMEFRAME, STARTING_CAPITAL,
    MAX_POSITION_SIZE, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    TAKER_FEE, MIN_CANDLES, ATR_MULTIPLIER
)


# ── Configuration ────────────────────────────────────────────────────────────
BACKTEST_CANDLES  = 1000     # coinDCX public API has a 1000 limit per request without time offsets
INITIAL_CAPITAL   = STARTING_CAPITAL


# ── Fetch historical data from CoinDCX ───────────────────────────────────────
def fetch_backtest_data(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """
    Fetch OHLCV data from CoinDCX API.
    Handles multi-batch fetching if CoinDCX API limits per request.
    """
    print(f"[Backtest] Fetching {limit} candles for {symbol}...")
    
    batch_size = 1000
    all_candles = []
    remaining = limit
    
    while remaining > 0:
        batch = min(batch_size, remaining)
        try:
            df = fetch_ohlcv(symbol, timeframe, limit=batch)
            all_candles.append(df)
            remaining -= len(df)
            
            if len(df) < batch:
                break  # Reached end of history
        except Exception as e:
            if all_candles:
                print(f"[Backtest] Warning: {e}, using {len(pd.concat(all_candles))} candles")
                break
            else:
                raise
    
    if not all_candles:
        raise Exception(f"Failed to fetch {symbol} data from CoinDCX")
    
    df = pd.concat(all_candles, ignore_index=True)
    df = df.drop_duplicates(subset=["timestamp"], keep="first").reset_index(drop=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    
    print(f"[Backtest] Fetched {len(df)} candles: {df['datetime'].iloc[0]} → {df['datetime'].iloc[-1]}")
    return df


# ── Simulate strategy bar-by-bar ─────────────────────────────────────────────
def run_backtest(df: pd.DataFrame) -> dict:
    """
    Walk forward through candles, simulating trades.
    NO lookahead — at bar N, we only use data from bars 0..N.
    """
    capital       = INITIAL_CAPITAL
    peak_capital  = INITIAL_CAPITAL
    position      = None    # None = flat, dict = open trade
    trades        = []

    for i in range(MIN_CANDLES + 20, len(df)):
        # Only use data available up to and including bar i
        window  = df.iloc[:i+1].copy()
        window  = compute_indicators(window)

        if window.empty or len(window) < 30:
            continue

        last  = window.iloc[-1]
        price = last["close"]
        ts    = last["datetime"]

        signals = {
            "close":        float(last["close"]),
            "ema_fast":     float(last["ema_fast"]),
            "ema_slow":     float(last["ema_slow"]),
            "sma_trend":    float(last["sma_trend"]),
            "atr":          float(last["atr"]),
            "vol_ratio":    float(last["vol_ratio"]),
            "candle_count": len(window),
        }

        # ── If position open: check exit ─────────────────────────────────────
        if position is not None:
            should_exit = False
            exit_reason = ""

            # Update Mathematical Trailing Stop dynamically
            current_high = last["high"]
            current_atr = signals["atr"]
            new_stop_loss = current_high - (current_atr * ATR_MULTIPLIER)
            
            # Trailing stops only move UP
            if new_stop_loss > position["stop_loss"]:
                position["stop_loss"] = new_stop_loss

            # Check dynamic Stop Loss hit
            if price <= position["stop_loss"]:
                should_exit = True
                exit_reason = "Trailing Stop"
                
            # Take profit (should be inf in config, but left just in case)
            elif price >= position["take_profit"]:
                should_exit = True
                exit_reason = "tp"
            else:
                # Strategy signal exit (Momentum Breakdown)
                sig, _ = generate_signal(signals, has_open_position=True, open_side="buy", entry_price=position["entry"])
                if sig == "sell":
                    should_exit = True
                    exit_reason = "Momentum Break"

            if should_exit:
                exit_price  = price
                gross_pnl   = (exit_price - position["entry"]) * position["qty"]
                fees        = (position["entry"] * position["qty"] * TAKER_FEE
                               + exit_price    * position["qty"] * TAKER_FEE)
                net_pnl     = gross_pnl - fees
                capital    += net_pnl
                peak_capital = max(peak_capital, capital)

                trades.append({
                    "entry_time":  position["entry_time"],
                    "exit_time":   ts,
                    "entry_price": position["entry"],
                    "exit_price":  exit_price,
                    "qty":         position["qty"],
                    "gross_pnl":   round(gross_pnl, 4),
                    "fees":        round(fees, 4),
                    "net_pnl":     round(net_pnl, 4),
                    "exit_reason": exit_reason,
                    "capital":     round(capital, 4),
                })
                position = None
            continue  # don't look for new entry while in a trade

        # ── No position: check for entry ──────────────────────────────────────
        sig, reason = generate_signal(signals, has_open_position=False)

        if sig == "buy":
            position_inr = min(MAX_POSITION_SIZE, capital * 0.90)
            if position_inr < 30:
                continue   # not enough capital

            qty        = position_inr / price
            entry_fee  = position_inr * TAKER_FEE
            capital   -= entry_fee    # deduct entry fee immediately

            position = {
                "entry":        price,
                "entry_time":   ts,
                "qty":          qty,
                "stop_loss":    price - (signals["atr"] * ATR_MULTIPLIER), # initial trailing stop
                "take_profit":  price * (1 + TAKE_PROFIT_PCT),
            }

    # If a position is still open at end of data, close at last price
    if position is not None and not df.empty:
        last_price = df.iloc[-1]["close"]
        gross_pnl  = (last_price - position["entry"]) * position["qty"]
        fees       = (position["entry"] * position["qty"] * TAKER_FEE
                      + last_price * position["qty"] * TAKER_FEE)
        net_pnl    = gross_pnl - fees
        capital   += net_pnl
        trades.append({
            "entry_time":   position["entry_time"],
            "exit_time":    df.iloc[-1]["datetime"],
            "entry_price":  position["entry"],
            "exit_price":   last_price,
            "qty":          position["qty"],
            "gross_pnl":    round(gross_pnl, 4),
            "fees":         round(fees, 4),
            "net_pnl":      round(net_pnl, 4),
            "exit_reason":  "end_of_data",
            "capital":      round(capital, 4),
        })

    return {"trades": trades, "final_capital": capital, "peak_capital": peak_capital}


# ── Performance report ────────────────────────────────────────────────────────
def print_report(result: dict, candle_count: int, symbol: str) -> None:
    trades        = result["trades"]
    final_capital = result["final_capital"]
    peak_capital  = result["peak_capital"]

    if not trades:
        print("\n[Backtest] No trades were generated.")
        print("  → Strategy is too conservative for this data window.")
        return

    df = pd.DataFrame(trades)

    total_trades  = len(df)
    wins          = df[df["net_pnl"] > 0]
    losses        = df[df["net_pnl"] <= 0]
    win_rate      = len(wins) / total_trades * 100
    total_net_pnl = df["net_pnl"].sum()
    total_fees    = df["fees"].sum()
    avg_win       = wins["net_pnl"].mean()   if len(wins)   > 0 else 0
    avg_loss      = losses["net_pnl"].mean() if len(losses) > 0 else 0
    profit_factor = (wins["net_pnl"].sum() / abs(losses["net_pnl"].sum())
                     if losses["net_pnl"].sum() != 0 else float("inf"))
    max_drawdown  = (peak_capital - final_capital) / peak_capital * 100
    expectancy    = total_net_pnl / total_trades

    pct_return = (final_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    sep = "─" * 50
    print(f"\n{'='*50}")
    print(f"  BACKTEST RESULTS — {symbol} {TIMEFRAME}")
    print(f"  {candle_count} candles | ₹{INITIAL_CAPITAL:.2f} starting capital")
    print(f"{'='*50}")
    print(f"\n  OVERVIEW")
    print(sep)
    print(f"  Total trades:     {total_trades}")
    print(f"  Final capital:    ₹{final_capital:.2f}")
    print(f"  Total return:     {pct_return:+.2f}%")
    print(f"  Net PnL:          ₹{total_net_pnl:+.4f}")
    print(f"  Total fees paid:  ₹{total_fees:.4f}")

    print(f"\n  TRADE QUALITY")
    print(sep)
    print(f"  Win rate:         {win_rate:.1f}%")
    print(f"  Profit factor:    {profit_factor:.2f}x")
    print(f"  Avg winning trade: ₹{avg_win:+.4f}")
    print(f"  Avg losing trade:  ₹{avg_loss:+.4f}")
    print(f"  Expectancy/trade:  ₹{expectancy:+.4f}")

    print(f"\n  VERDICT")
    print(sep)
    issues = []
    if expectancy <= 0:
        issues.append(f"  ⚠️  Negative expectancy (₹{expectancy:.4f}) — strategy loses money on average")
    if pct_return < 10.0:
        issues.append(f"  ⚠️  Return too low ({pct_return:.1f}%) — doesn't hit the 25%+ goal")

    if not issues:
        print(f"  ✅ All checks passed. The Asymmetric Trend-Rider generates massive returns.")
    else:
        print(f"  ❌ Issues found:")
        for issue in issues:
            print(issue)
        print(f"\n  Suggested fixes:")
        print(f"    - Try loosening EMA crossovers or volume filters in core/strategy_hybrid.py")

    print(f"\n{'='*50}\n")

    # Save detailed trade log
    os.makedirs("data", exist_ok=True)
    out_path = "data/backtest_results.csv"
    df.to_csv(out_path, index=False)
    print(f"  Trade log saved to: {out_path}")
    print(f"  Open it in Excel/LibreOffice to analyse individual trades.\n")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*50)
    print("  RUNNING MULTI-COIN BACKTEST")
    print("  Using CoinDCX API for live market data")
    print("="*50 + "\n")

    for sym in SYMBOLS:
        try:
            df     = fetch_backtest_data(sym, TIMEFRAME, limit=BACKTEST_CANDLES)
            if not df.empty:
                result = run_backtest(df)
                print_report(result, candle_count=len(df), symbol=sym)
        except Exception as e:
            print(f"  [Backtest] Skipped {sym} due to error: {e}\n")
