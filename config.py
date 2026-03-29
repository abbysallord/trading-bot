# config.py — Central configuration for all bot parameters
# Edit values here. Never hardcode these elsewhere in the codebase.

import os
from dotenv import load_dotenv

load_dotenv()

# ── Exchange ────────────────────────────────────────────────────────────────
EXCHANGE_ID        = "coindcx"
API_KEY            = os.getenv("COINDCX_API_KEY", "")
SECRET_KEY         = os.getenv("COINDCX_SECRET_KEY", "")

# Trading pairs (High Volatility List)
SYMBOLS            = ["SOL/INR", "SHIB/USDT", "DOGE/INR", "XRP/INR"]
TIMEFRAME          = "1h"          # 1-hour candles

# ── LLM Integration ─────────────────────────────────────────────────────────
MISTRAL_API_KEY    = os.getenv("MISTRAL_API_KEY", "")

# ── Capital & Position Sizing ───────────────────────────────────────────────
STARTING_CAPITAL   = 5000.0        # INR — your total deployed capital
MAX_POSITION_SIZE  = 1500.0        # INR — max value of a single trade (30%)
MAX_CONCURRENT     = 1             # Only 1 open position at a time

# ── Risk Guardrails (hard limits — do not loosen these early on) ────────────
DAILY_LOSS_LIMIT   = 1000.0        # INR — bot halts for the day if hit (20%)
MAX_DRAWDOWN_PCT   = 0.35          # 35% drawdown from peak → full stop
STOP_LOSS_PCT      = 0.05          # 5% stop-loss per trade (volatile coins)
TAKE_PROFIT_PCT    = 0.12          # 12% take-profit per trade (high reward)
MAX_TRADES_PER_DAY = 20            # Fee erosion control
COOLDOWN_SECONDS   = 300           # 5-min cooldown after a losing trade

# ── Strategy Parameters (Bollinger Band Mean Reversion) ────────────────────
BB_PERIOD          = 30            # Bollinger Band rolling window (longer to avoid fakeouts)
BB_STD             = 2.5           # Standard deviations for bands (extreme crashes only)
RSI_PERIOD         = 14            # RSI period
RSI_OVERSOLD       = 30            # Buy signal threshold (strict: < 30 for primary entry)
RSI_OVERBOUGHT     = 70            # Sell signal threshold (strict: > 62 for overbought)
MIN_CANDLES        = 50            # Minimum candles needed before trading starts

# ── Fees ───────────────────────────────────────────────────────────────────
MAKER_FEE          = 0.001         # 0.1% maker fee
TAKER_FEE          = 0.001         # 0.1% taker fee
ROUND_TRIP_FEE     = MAKER_FEE + TAKER_FEE  # 0.2% — minimum profit needed per trade

# ── Database ───────────────────────────────────────────────────────────────
DB_PATH            = "data/market.db"

# ── Telegram Alerts (optional — fill in .env when ready) ───────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
ALERTS_ENABLED     = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# ── Operational Mode ───────────────────────────────────────────────────────
# "paper"  → runs full logic, logs trades, but never places real orders
# "live"   → places real orders on the exchange
# Start with "paper". Only switch to "live" after consistent paper profits.
TRADING_MODE       = "live"