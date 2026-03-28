# core/alerts.py — Telegram notifications
#
# Sends trade alerts and daily summaries to your phone.
# Free via Telegram Bot API — no paid service needed.
#
# Setup (do this after the bot is running):
#   1. Message @BotFather on Telegram → /newbot → copy the token
#   2. Message your new bot, then visit:
#      https://api.telegram.org/bot<TOKEN>/getUpdates
#      to get your chat_id
#   3. Add both to .env as TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
#
# If ALERTS_ENABLED=False in config, all calls are silent no-ops.

import asyncio
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ALERTS_ENABLED, TRADING_MODE


def _send(message: str) -> None:
    """Send a message via Telegram Bot API (synchronous, fire-and-forget)."""
    if not ALERTS_ENABLED:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML",
        }
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code != 200:
            print(f"[Alerts] Telegram send failed: {response.text}")
    except Exception as e:
        print(f"[Alerts] Telegram error (non-fatal): {e}")


def alert_trade_opened(side: str, price: float, quantity: float,
                       position_value: float, stop_loss: float,
                       take_profit: float, reason: str) -> None:
    mode_tag = "📋 PAPER" if TRADING_MODE == "paper" else "🔴 LIVE"
    emoji    = "🟢" if side == "buy" else "🔴"
    msg = (
        f"{mode_tag} | {emoji} <b>TRADE OPENED</b>\n"
        f"Side:     {side.upper()}\n"
        f"Price:    ₹{price:,.2f}\n"
        f"Qty:      {quantity:.6f}\n"
        f"Value:    ₹{position_value:.2f}\n"
        f"SL:       ₹{stop_loss:,.2f}\n"
        f"TP:       ₹{take_profit:,.2f}\n"
        f"Signal:   {reason}"
    )
    _send(msg)
    print(f"[Alerts] Trade opened alert sent.")


def alert_trade_closed(side: str, entry_price: float, exit_price: float,
                       net_pnl: float, exit_reason: str,
                       capital_remaining: float) -> None:
    mode_tag = "📋 PAPER" if TRADING_MODE == "paper" else "🔴 LIVE"
    pnl_emoji = "✅" if net_pnl >= 0 else "❌"
    reason_map = {"tp": "Take Profit", "sl": "Stop Loss",
                  "signal": "Signal Exit", "eod": "End of Day", "manual": "Manual"}
    reason_str = reason_map.get(exit_reason, exit_reason)

    msg = (
        f"{mode_tag} | {pnl_emoji} <b>TRADE CLOSED</b> — {reason_str}\n"
        f"Side:     {side.upper()}\n"
        f"Entry:    ₹{entry_price:,.2f}\n"
        f"Exit:     ₹{exit_price:,.2f}\n"
        f"Net PnL:  ₹{net_pnl:+.4f}\n"
        f"Capital:  ₹{capital_remaining:.2f}"
    )
    _send(msg)


def alert_risk_halt(reason: str, capital: float) -> None:
    msg = (
        f"🚨 <b>BOT HALTED</b>\n"
        f"Reason:  {reason}\n"
        f"Capital: ₹{capital:.2f}\n\n"
        f"Manual review required before restarting."
    )
    _send(msg)


def alert_daily_summary(trades: int, wins: int, losses: int,
                         gross_pnl: float, fees: float,
                         net_pnl: float, capital: float) -> None:
    win_rate = (wins / trades * 100) if trades > 0 else 0
    msg = (
        f"📊 <b>DAILY SUMMARY</b>\n"
        f"Trades:   {trades} ({wins}W / {losses}L)\n"
        f"Win rate: {win_rate:.0f}%\n"
        f"Gross:    ₹{gross_pnl:+.4f}\n"
        f"Fees:     ₹{fees:.4f}\n"
        f"Net:      ₹{net_pnl:+.4f}\n"
        f"Capital:  ₹{capital:.2f}"
    )
    _send(msg)


def alert_startup(mode: str, symbol: str, capital: float) -> None:
    emoji = "📋" if mode == "paper" else "🔴"
    msg = (
        f"{emoji} <b>BOT STARTED</b>\n"
        f"Mode:    {mode.upper()}\n"
        f"Symbol:  {symbol}\n"
        f"Capital: ₹{capital:.2f}"
    )
    _send(msg)
