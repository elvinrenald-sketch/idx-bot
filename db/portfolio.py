import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "local_data", "portfolio.db")

def init_portfolio_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table to track deposits and withdrawals to calculate total equity
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cash_flow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            action TEXT CHECK( action IN ('DEPOSIT', 'WITHDRAWAL') ),
            amount REAL
        )
    ''')

    # Table to track historical trades (Buy/Sell)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            action TEXT CHECK( action IN ('BUY', 'SELL') ),
            price REAL,
            lots INTEGER
        )
    ''')
    
    # Materialized view/table for current holdings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS holdings (
            ticker TEXT PRIMARY KEY,
            average_price REAL,
            total_lots INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()

def add_trade(ticker: str, action: str, price: float, lots: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO trades (ticker, action, price, lots) VALUES (?, ?, ?, ?)",
        (ticker.upper(), action.upper(), price, lots)
    )
    
    # Update Holdings
    cursor.execute("SELECT average_price, total_lots FROM holdings WHERE ticker = ?", (ticker.upper(),))
    row = cursor.fetchone()
    
    if action.upper() == 'BUY':
        if row:
            current_avg_price, current_lots = row
            new_total_lots = current_lots + lots
            new_avg_price = ((current_avg_price * current_lots) + (price * lots)) / new_total_lots
            cursor.execute(
                "UPDATE holdings SET average_price = ?, total_lots = ? WHERE ticker = ?",
                (new_avg_price, new_total_lots, ticker.upper())
            )
        else:
            cursor.execute(
                "INSERT INTO holdings (ticker, average_price, total_lots) VALUES (?, ?, ?)",
                (ticker.upper(), price, lots)
            )
    elif action.upper() == 'SELL':
        if row:
            current_avg_price, current_lots = row
            new_total_lots = current_lots - lots
            if new_total_lots <= 0:
                cursor.execute("DELETE FROM holdings WHERE ticker = ?", (ticker.upper(),))
            else:
                cursor.execute(
                    "UPDATE holdings SET total_lots = ? WHERE ticker = ?",
                    (new_total_lots, ticker.upper())
                )
    
    conn.commit()
    conn.close()

def get_holdings():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT ticker, average_price, total_lots FROM holdings")
    rows = cursor.fetchall()
    conn.close()
    
    holdings = []
    for row in rows:
        holdings.append({
            "ticker": row[0],
            "average_price": row[1],
            "total_lots": row[2]
        })
    return holdings

def log_cash_flow(action: str, amount: float):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO cash_flow (action, amount) VALUES (?, ?)",
        (action.upper(), amount)
    )
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_portfolio_db()
    print("Portfolio database initialized.")
