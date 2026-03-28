#!/usr/bin/env python3
# backtest/run_backtest.py — Strategy backtester
#
# Run this BEFORE switching to live mode. If this doesn't show
# consistent positive expectancy, the strategy needs tuning.
#
# Usage:
#   python backtest/run_backtest.py
#
# What it does:
#   1. Fetches up to 1000 historical 1-minute candles from CoinDCX (free, no API key needed for public data)
#   2. Computes indicators on the full history
#   3. Simulates the strategy bar-by-bar (no lookahead bias)
#   4. Applies realistic fees (0.1% per side)
#   5. Prints a full performance report
#   6. Saves results to data/backtest_results.csv for further analysis
#
# How to interpret results:
#   Win rate > 50%      → strategy finds edge more often than not
#   Profit factor > 1.3 → gross wins meaningfully exceed gross losses
#   Max drawdown < 20%  → strategy doesn't blow up during bad streaks
#   Expectancy > 0      → positive average PnL per trade after fees
#
# If any of these fail, DO NOT switch to live mode. Tune config.py first.

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
    TAKER_FEE, RSI_OVERSOLD, RSI_OVERBOUGHT,
    BB_PERIOD, BB_STD
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
    
    # CoinDCX API may limit to 1000 per request, so we fetch in batches
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
    
    print(f"[Backtest] Fetched {len(df)} candles: "
          f"{df['datetime'].iloc[0]} → {df['datetime'].iloc[-1]}")
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

    for i in range(BB_PERIOD + 20, len(df)):
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
            "rsi":          float(last["rsi"]),
            "bb_pct":       float(last["bb_pct"]),
            "bb_lower":     float(last["bb_lower"]),
            "bb_upper":     float(last["bb_upper"]),
            "bb_mid":       float(last["bb_mid"]),
            "bb_width":     float(last["bb_width"]),
            "atr":          float(last["atr"]),
            "vol_ratio":    float(last["vol_ratio"]),
            "sma20":        float(last["sma20"]),
            "sma50":        float(last["sma50"]),
            "candle_count": len(window),
        }

        # ── If position open: check exit ─────────────────────────────────────
        if position is not None:
            should_exit = False
            exit_reason = ""

            # Stop loss
            if price <= position["stop_loss"]:
                should_exit = True
                exit_reason = "sl"
            # Take profit
            elif price >= position["take_profit"]:
                should_exit = True
                exit_reason = "tp"
            else:
                # Strategy signal exit
                sig, _ = generate_signal(signals, has_open_position=True, open_side="buy", entry_price=position["entry"])
                if sig == "sell":
                    should_exit = True
                    exit_reason = "signal"

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
                    "rsi_entry":   position["rsi_entry"],
                    "bb_pct_entry": position["bb_pct_entry"],
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
                "stop_loss":    price * (1 - STOP_LOSS_PCT),
                "take_profit":  price * (1 + TAKE_PROFIT_PCT),
                "rsi_entry":    signals["rsi"],
                "bb_pct_entry": signals["bb_pct"],
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
            "rsi_entry":    position["rsi_entry"],
            "bb_pct_entry": position["bb_pct_entry"],
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
        print("  → Try loosening RSI_OVERSOLD or BB thresholds in config.py")
        return

    df = pd.DataFrame(trades)

    total_trades  = len(df)
    wins          = df[df["net_pnl"] > 0]
    losses        = df[df["net_pnl"] <= 0]
    win_rate      = len(wins) / total_trades * 100
    total_net_pnl = df["net_pnl"].sum()
    total_fees    = df["fees"].sum()
    total_gross   = df["gross_pnl"].sum()
    avg_win       = wins["net_pnl"].mean()   if len(wins)   > 0 else 0
    avg_loss      = losses["net_pnl"].mean() if len(losses) > 0 else 0
    profit_factor = (wins["net_pnl"].sum() / abs(losses["net_pnl"].sum())
                     if losses["net_pnl"].sum() != 0 else float("inf"))
    max_drawdown  = (peak_capital - final_capital) / peak_capital * 100
    expectancy    = total_net_pnl / total_trades

    tp_exits  = len(df[df["exit_reason"] == "tp"])
    sl_exits  = len(df[df["exit_reason"] == "sl"])
    sig_exits = len(df[df["exit_reason"] == "signal"])

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

    print(f"\n  EXIT BREAKDOWN")
    print(sep)
    print(f"  Take profit hits: {tp_exits}  ({tp_exits/total_trades*100:.0f}%)")
    print(f"  Stop loss hits:   {sl_exits}  ({sl_exits/total_trades*100:.0f}%)")
    print(f"  Signal exits:     {sig_exits}  ({sig_exits/total_trades*100:.0f}%)")

    print(f"\n  RISK METRICS")
    print(sep)
    print(f"  Max drawdown:     {max_drawdown:.1f}%")
    print(f"  Peak capital:     ₹{peak_capital:.2f}")

    print(f"\n  VERDICT")
    print(sep)
    issues = []
    if win_rate < 50:
        issues.append(f"  ⚠️  Win rate {win_rate:.1f}% < 50% — strategy loses more than it wins")
    if profit_factor < 1.3:
        issues.append(f"  ⚠️  Profit factor {profit_factor:.2f} < 1.3 — edge is too thin")
    if max_drawdown > 20:
        issues.append(f"  ⚠️  Max drawdown {max_drawdown:.1f}% > 20% — too much risk")
    if expectancy <= 0:
        issues.append(f"  ⚠️  Negative expectancy (₹{expectancy:.4f}) — strategy loses money on average")
    if total_trades < 10:
        issues.append(f"  ⚠️  Only {total_trades} trades — not enough data to be statistically meaningful")

    if not issues:
        print(f"  ✅ All checks passed. Strategy shows positive expectancy.")
        print(f"     You can proceed to extended paper trading.")
    else:
        print(f"  ❌ Issues found — do NOT go live yet:")
        for issue in issues:
            print(issue)
        print(f"\n  Suggested fixes:")
        print(f"    - Run on more candles (fetch 2000+ if API allows)")
        print(f"    - Adjust RSI_OVERSOLD, BB_STD in config.py")
        print(f"    - Try different SYMBOLS in config.py")

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
