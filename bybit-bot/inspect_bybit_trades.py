import sqlite3
import pandas as pd
from datetime import datetime

DB_PATH = "/Users/oliveaprilia/Documents/workspace antigravity ai/bybit-bot/trades.db"

def inspect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Query closed positions
    df_closed = pd.read_sql_query(
        "SELECT id, symbol, side, entry_price, sl_price, tp_price, exit_price, pnl, status, close_reason, open_ts, close_ts FROM positions WHERE status='CLOSED' ORDER BY close_ts DESC LIMIT 20",
        conn
    )
    
    # Query open positions
    df_open = pd.read_sql_query(
        "SELECT id, symbol, side, entry_price, sl_price, tp_price, open_ts FROM positions WHERE status='OPEN'",
        conn
    )
    
    print("=== OPEN POSITIONS ===")
    if len(df_open) == 0:
        print("No open positions.")
    else:
        print(df_open.to_string(index=False))
        
    print("\n=== RECENT CLOSED POSITIONS ===")
    if len(df_closed) == 0:
        print("No recent closed positions.")
    else:
        print(df_closed.to_string(index=False))
        
    # Summarize PnL by side
    summary = pd.read_sql_query(
        "SELECT side, status, COUNT(*) as count, SUM(pnl) as total_pnl, AVG(pnl) as avg_pnl FROM positions GROUP BY side, status",
        conn
    )
    print("\n=== SUMMARY BY SIDE & STATUS ===")
    print(summary.to_string(index=False))
    
    conn.close()

if __name__ == "__main__":
    inspect()
