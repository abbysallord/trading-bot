# Trading Bot — Setup & Run Guide

## Final folder structure

```
trading_bot/
├── .env                        ← your API keys (create this yourself)
├── .gitignore
├── config.py                   ← all settings live here
├── main.py                     ← run this to start the bot
├── core/
│   ├── __init__.py
│   ├── alerts.py               ← Telegram alerts (optional)
│   ├── database.py             ← SQLite storage
│   ├── exchange.py             ← CoinDCX connection + live feed
│   ├── executor.py             ← order placement wrapper
│   ├── indicators.py           ← Bollinger Bands, RSI, ATR
│   ├── risk.py                 ← hard guardrails (all 8 checks)
│   └── strategy.py             ← signal generation logic
├── backtest/
│   ├── __init__.py
│   └── run_backtest.py         ← run this BEFORE going live
└── data/
    ├── market.db               ← auto-created by SQLite on first run
    └── backtest_results.csv    ← auto-created after running backtest
```

---

## Step 1 — Install Python dependencies

Open a terminal in your `trading_bot/` folder, activate your venv, then:

```bash
pip install ccxt pandas pandas-ta scikit-learn lightgbm \
    backtesting vectorbt sqlalchemy python-dotenv \
    aiohttp websockets requests
```

> Note: `python-telegram-bot` is NOT needed. `alerts.py` uses the
> plain `requests` library, which is already in the list above.

---

## Step 2 — Create your .env file

Create a file called `.env` in the root `trading_bot/` folder:

```
COINDCX_API_KEY=paste_your_key_here
COINDCX_SECRET_KEY=paste_your_secret_here
```

Leave Telegram fields out entirely — the bot works fine without them.
If you want alerts later, add:
```
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## Step 3 — Run the backtest first (no API key needed)

The backtest uses public CoinDCX market data — your API key is not
required for this step. Run it before anything else:

```bash
python backtest/run_backtest.py
```

You'll see a full performance report. Look for:
- Win rate > 50%
- Profit factor > 1.3
- Max drawdown < 20%
- Positive expectancy per trade

If these pass, move to Step 4. If not, adjust `config.py` and rerun.

---

## Step 4 — Run the bot in paper mode

Paper mode runs the full strategy and logs every "trade" to SQLite,
but never places a real order. This is the default.

```bash
python main.py
```

What you'll see in the terminal:

```
============================================================
  CoinDCX Trading Bot
  Mode:    PAPER
  Symbol:  BTC/INR
  Capital: ₹500.00
  Started: 2026-03-22 10:45:00
============================================================

[DB] Database initialised.
[Exchange] Fetching 500 historical candles for BTC/INR...
[Exchange] Stored 498 new candles. Total in DB: 498
[Main] 498 candles loaded. Indicators ready.
[Main] Starting live candle feed...

[2026-03-22 10:46:00] Price: ₹7,234,500 | RSI 42.3 — neutral | BB%=0.38
         Capital: ₹500.00 | Drawdown: 0.0% | Daily PnL: ₹+0.00 | FLAT
         Signal: HOLD | Strength: 0.12 | No signal: BB%=0.38, RSI=42.1
```

Press `Ctrl+C` to stop cleanly.

---

## Step 5 — Check your paper trades

After running for a few hours, inspect what the bot has been doing:

```bash
# Open SQLite directly
sqlite3 data/market.db

# Inside sqlite3:
.mode column
.headers on
SELECT id, side, entry_price, exit_price, net_pnl_inr, exit_reason
FROM trades ORDER BY id DESC LIMIT 20;

.quit
```

Or open `data/market.db` with DB Browser for SQLite (free GUI app).

---

## Step 6 — Going live (only after paper trading looks good)

When paper mode shows consistent positive PnL over several days,
open `config.py` and change ONE line:

```python
TRADING_MODE = "live"   # was "paper"
```

Then run `python main.py` again. You'll see a 5-second warning with
a chance to abort before any real order is placed.

---

## Telegram alerts (completely optional)

To get trade notifications on your phone:
1. Message `@BotFather` on Telegram → `/newbot` → copy the token
2. Send any message to your new bot
3. Visit: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Find `"chat": {"id": 123456}` — that number is your chat ID
5. Add both to `.env`

The bot works identically with or without this. Every alert call
is a silent no-op when the tokens are missing.

---

## Common errors and fixes

**`ModuleNotFoundError: No module named 'ccxt'`**
→ Your venv isn't activated. Run `source venv/bin/activate` first.

**`ccxt.errors.AuthenticationError`**
→ API key or secret is wrong in `.env`. Double-check for spaces.

**`No historical data returned`**
→ CoinDCX might not support `BTC/INR` via ccxt's default symbol format.
  Try changing `SYMBOL = "BTC/USDT"` in `config.py` temporarily to test.

**Bot prints HOLD on every candle and never trades**
→ Normal behaviour until a genuine mean reversion setup appears.
  BTC can go hours without touching a Bollinger Band.
  Check the backtest to confirm signals do occur in historical data.

**`sqlite3.OperationalError: no such table`**
→ Delete `data/market.db` and restart — it will be recreated cleanly.
