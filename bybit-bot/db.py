"""
Bybit Crypto Algo Bot — Database Layer
SQLite for positions, trade history, and equity tracking.
"""
import sqlite3
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional
from config import DB_PATH, DATA_DIR

log = logging.getLogger('db')


def _connect() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            bybit_symbol    TEXT NOT NULL,
            side            TEXT NOT NULL DEFAULT 'Buy',
            entry_price     REAL NOT NULL,
            qty             REAL NOT NULL,
            leverage        INTEGER NOT NULL,
            sl_price        REAL,
            tp_price        REAL,
            margin_used     REAL,
            status          TEXT NOT NULL DEFAULT 'OPEN',
            exit_price      REAL,
            pnl             REAL,
            pnl_pct         REAL,
            close_reason    TEXT,
            signal_data     TEXT,
            timeframe       TEXT,
            open_ts         TEXT NOT NULL,
            close_ts        TEXT,
            alpha_pct       REAL,
            volume_ratio    REAL
        );

        CREATE TABLE IF NOT EXISTS equity_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT NOT NULL,
            equity  REAL NOT NULL,
            balance REAL NOT NULL,
            open_positions INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS scan_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ts           TEXT NOT NULL,
            total_coins  INTEGER,
            alpha_coins  INTEGER,
            signals      INTEGER,
            scan_time_ms INTEGER
        );
    """)
    conn.commit()
    conn.close()
    log.info(f"Database initialized: {DB_PATH}")


# ── POSITIONS ────────────────────────────────────────────────

def open_position(symbol: str, bybit_symbol: str, entry_price: float,
                  qty: float, leverage: int, sl_price: float, tp_price: float,
                  margin_used: float, timeframe: str, alpha_pct: float,
                  volume_ratio: float, signal_data: str = '') -> int:
    """Record a new open position. Returns position ID."""
    conn = _connect()
    cur = conn.execute("""
        INSERT INTO positions
            (symbol, bybit_symbol, side, entry_price, qty, leverage,
             sl_price, tp_price, margin_used, status, signal_data,
             timeframe, open_ts, alpha_pct, volume_ratio)
        VALUES (?, ?, 'Buy', ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?)
    """, (symbol, bybit_symbol, entry_price, qty, leverage,
          sl_price, tp_price, margin_used, signal_data,
          timeframe, datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
          alpha_pct, volume_ratio))
    conn.commit()
    pos_id = cur.lastrowid
    conn.close()
    log.info(f"DB OPEN #{pos_id}: {bybit_symbol} @ {entry_price:.6f} "
             f"qty={qty} lev={leverage}x SL={sl_price:.6f} TP={tp_price:.6f}")
    return pos_id


def close_position(pos_id: int, exit_price: float, reason: str) -> Optional[Dict]:
    """Close a position and calculate PnL. Returns position dict."""
    conn = _connect()
    row = conn.execute("SELECT * FROM positions WHERE id=? AND status='OPEN'",
                       (pos_id,)).fetchone()
    if not row:
        conn.close()
        return None

    entry = row['entry_price']
    qty = row['qty']
    leverage = row['leverage']

    # PnL calculation for LONG
    pnl = (exit_price - entry) * qty
    pnl_pct = ((exit_price - entry) / entry) * 100 * leverage  # leveraged PnL%

    conn.execute("""
        UPDATE positions SET
            status='CLOSED', exit_price=?, pnl=?, pnl_pct=?,
            close_reason=?, close_ts=?
        WHERE id=?
    """, (exit_price, pnl, pnl_pct, reason,
          datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), pos_id))
    conn.commit()

    result = dict(row)
    result['exit_price'] = exit_price
    result['pnl'] = pnl
    result['pnl_pct'] = pnl_pct
    result['close_reason'] = reason
    conn.close()

    emoji = '✅' if pnl >= 0 else '❌'
    log.info(f"DB CLOSE #{pos_id} {emoji}: {row['bybit_symbol']} "
             f"entry={entry:.6f} exit={exit_price:.6f} "
             f"PnL=${pnl:.4f} ({pnl_pct:+.2f}%) reason={reason}")
    return result


def get_open_positions() -> List[Dict]:
    """Get all open positions."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM positions WHERE status='OPEN' ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_open_symbols() -> set:
    """Get set of symbols that have open positions."""
    conn = _connect()
    rows = conn.execute(
        "SELECT DISTINCT bybit_symbol FROM positions WHERE status='OPEN'"
    ).fetchall()
    conn.close()
    return {r['bybit_symbol'] for r in rows}


def count_open() -> int:
    """Count open positions."""
    conn = _connect()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM positions WHERE status='OPEN'"
    ).fetchone()
    conn.close()
    return row['cnt']


def update_sl(pos_id: int, new_sl: float):
    """Update stop loss price for trailing stop."""
    conn = _connect()
    conn.execute("UPDATE positions SET sl_price=? WHERE id=?", (new_sl, pos_id))
    conn.commit()
    conn.close()


def get_stats() -> Dict:
    """Get trading statistics."""
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) as c FROM positions WHERE status='CLOSED'").fetchone()['c']
    wins = conn.execute("SELECT COUNT(*) as c FROM positions WHERE status='CLOSED' AND pnl > 0").fetchone()['c']
    losses = conn.execute("SELECT COUNT(*) as c FROM positions WHERE status='CLOSED' AND pnl <= 0").fetchone()['c']
    total_pnl = conn.execute("SELECT COALESCE(SUM(pnl), 0) as s FROM positions WHERE status='CLOSED'").fetchone()['s']
    open_count = conn.execute("SELECT COUNT(*) as c FROM positions WHERE status='OPEN'").fetchone()['c']

    best = conn.execute("SELECT MAX(pnl_pct) as m FROM positions WHERE status='CLOSED'").fetchone()['m'] or 0
    worst = conn.execute("SELECT MIN(pnl_pct) as m FROM positions WHERE status='CLOSED'").fetchone()['m'] or 0

    conn.close()
    return {
        'total_trades': total,
        'wins': wins,
        'losses': losses,
        'win_rate': (wins / total * 100) if total > 0 else 0,
        'total_pnl': total_pnl,
        'open_positions': open_count,
        'best_trade_pct': best,
        'worst_trade_pct': worst,
    }


def get_recent_trades(limit: int = 20) -> List[Dict]:
    """Get recent closed trades."""
    conn = _connect()
    rows = conn.execute("""
        SELECT * FROM positions WHERE status='CLOSED'
        ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_equity(equity: float, balance: float, open_pos: int):
    """Log equity snapshot."""
    conn = _connect()
    conn.execute("""
        INSERT INTO equity_log (ts, equity, balance, open_positions)
        VALUES (?, ?, ?, ?)
    """, (datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
          equity, balance, open_pos))
    conn.commit()
    conn.close()


def log_scan(total_coins: int, alpha_coins: int, signals: int, scan_time_ms: int):
    """Log scan result."""
    conn = _connect()
    conn.execute("""
        INSERT INTO scan_log (ts, total_coins, alpha_coins, signals, scan_time_ms)
        VALUES (?, ?, ?, ?, ?)
    """, (datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
          total_coins, alpha_coins, signals, scan_time_ms))
    conn.commit()
    conn.close()


def get_equity_curve(limit: int = 100) -> List[Dict]:
    """Get equity history."""
    conn = _connect()
    rows = conn.execute(
        "SELECT ts, equity, balance FROM equity_log ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]
