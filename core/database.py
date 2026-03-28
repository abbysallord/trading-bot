# core/database.py — SQLite storage for candles, trades, and bot state
#
# Two tables:
#   candles     — raw OHLCV data, one row per 1-minute candle
#   trades      — every trade the bot takes (paper or live)
#   bot_state   — persistent state (daily PnL, drawdown tracking)

import os
import sqlite3
import pandas as pd
from datetime import datetime, date
from typing import Optional
from config import DB_PATH


def _connect() -> sqlite3.Connection:
    """Return a new SQLite connection with row_factory set."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS candles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT    NOT NULL,
                timestamp   INTEGER NOT NULL,   -- Unix ms, open time of candle
                open        REAL    NOT NULL,
                high        REAL    NOT NULL,
                low         REAL    NOT NULL,
                close       REAL    NOT NULL,
                volume      REAL    NOT NULL,
                UNIQUE(symbol, timestamp)       -- no duplicate candles
            );

            CREATE INDEX IF NOT EXISTS idx_candles_symbol_ts
                ON candles (symbol, timestamp DESC);

            CREATE TABLE IF NOT EXISTS trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT    NOT NULL,
                mode            TEXT    NOT NULL,  -- 'paper' or 'live'
                side            TEXT    NOT NULL,  -- 'buy' or 'sell'
                entry_price     REAL,
                exit_price      REAL,
                quantity        REAL    NOT NULL,
                position_value  REAL    NOT NULL,  -- INR value at entry
                stop_loss       REAL    NOT NULL,
                take_profit     REAL    NOT NULL,
                entry_time      TEXT,
                exit_time       TEXT,
                pnl_inr         REAL    DEFAULT 0,
                fees_inr        REAL    DEFAULT 0,
                net_pnl_inr     REAL    DEFAULT 0,
                exit_reason     TEXT,   -- 'tp', 'sl', 'signal', 'eod', 'manual'
                signal_rsi      REAL,
                signal_bb_pct   REAL,   -- price position within BB (0=lower, 1=upper)
                notes           TEXT
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                key     TEXT PRIMARY KEY,
                value   TEXT NOT NULL
            );
        """)
    print("[DB] Database initialised.")


# ── Candle operations ───────────────────────────────────────────────────────

def insert_candle(symbol: str, ts: int, o: float, h: float,
                  l: float, c: float, v: float) -> None:
    """Insert a single OHLCV candle. Silently ignores duplicates."""
    with _connect() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO candles
                (symbol, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (symbol, ts, o, h, l, c, v))


def insert_candles_bulk(symbol: str, df: pd.DataFrame) -> int:
    """
    Bulk-insert a DataFrame of candles.
    DataFrame must have columns: timestamp, open, high, low, close, volume
    Returns number of new rows inserted.
    """
    rows = [
        (symbol, int(row.timestamp), row.open, row.high, row.low, row.close, row.volume)
        for _, row in df.iterrows()
    ]
    with _connect() as conn:
        cursor = conn.executemany("""
            INSERT OR IGNORE INTO candles
                (symbol, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return cursor.rowcount


def get_recent_candles(symbol: str, limit: int = 200) -> pd.DataFrame:
    """
    Fetch the most recent N candles for a symbol, sorted oldest→newest.
    Returns a DataFrame ready for indicator computation.
    """
    with _connect() as conn:
        rows = conn.execute("""
            SELECT timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (symbol, limit)).fetchall()

    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame([dict(r) for r in rows])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def get_candle_count(symbol: str) -> int:
    """Return total number of stored candles for a symbol."""
    with _connect() as conn:
        result = conn.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol = ?", (symbol,)
        ).fetchone()
    return result[0] if result else 0


# ── Trade operations ────────────────────────────────────────────────────────

def open_trade(symbol: str, mode: str, side: str, entry_price: float,
               quantity: float, position_value: float, stop_loss: float,
               take_profit: float, rsi: Optional[float] = None,
               bb_pct: Optional[float] = None) -> int:
    """Log a new trade opening. Returns the trade ID."""
    with _connect() as conn:
        cursor = conn.execute("""
            INSERT INTO trades
                (symbol, mode, side, entry_price, quantity, position_value,
                 stop_loss, take_profit, entry_time, signal_rsi, signal_bb_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, mode, side, entry_price, quantity, position_value,
              stop_loss, take_profit,
              datetime.utcnow().isoformat(), rsi, bb_pct))
        return cursor.lastrowid


def close_trade(trade_id: int, exit_price: float, exit_reason: str,
                fees_inr: float) -> None:
    """Update an existing trade with exit data and compute PnL."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT entry_price, quantity, position_value, side FROM trades WHERE id = ?",
            (trade_id,)
        ).fetchone()
        if not row:
            print(f"[DB] Warning: trade_id {trade_id} not found for closing.")
            return

        entry_price   = row["entry_price"]
        quantity      = row["quantity"]
        side          = row["side"]

        if side == "buy":
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity

        net_pnl = pnl - fees_inr

        conn.execute("""
            UPDATE trades SET
                exit_price  = ?,
                exit_time   = ?,
                pnl_inr     = ?,
                fees_inr    = ?,
                net_pnl_inr = ?,
                exit_reason = ?
            WHERE id = ?
        """, (exit_price, datetime.utcnow().isoformat(),
              round(pnl, 4), round(fees_inr, 4),
              round(net_pnl, 4), exit_reason, trade_id))


def get_daily_pnl(for_date: Optional[date] = None) -> float:
    """Return total net PnL for today (or a specific date)."""
    target = (for_date or date.today()).isoformat()
    with _connect() as conn:
        result = conn.execute("""
            SELECT COALESCE(SUM(net_pnl_inr), 0)
            FROM trades
            WHERE DATE(exit_time) = ?
        """, (target,)).fetchone()
    return result[0] if result else 0.0


def get_trade_count_today() -> int:
    """Return number of closed trades today."""
    today = date.today().isoformat()
    with _connect() as conn:
        result = conn.execute("""
            SELECT COUNT(*) FROM trades
            WHERE DATE(exit_time) = ?
        """, (today,)).fetchone()
    return result[0] if result else 0


def get_all_trades(limit: int = 100) -> pd.DataFrame:
    """Fetch recent closed trades as a DataFrame for analysis."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM trades
            WHERE exit_time IS NOT NULL
            ORDER BY exit_time DESC
            LIMIT ?
        """, (limit,)).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


# ── Bot state (persistent key-value) ───────────────────────────────────────

def set_state(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO bot_state (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))


def get_state(key: str, default: str = "") -> str:
    with _connect() as conn:
        result = conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (key,)
        ).fetchone()
    return result[0] if result else default
