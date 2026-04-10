import sqlite3
import json
from datetime import datetime, timezone

DB_PATH = "/Users/oliveaprilia/polymarket-scanner/journal/trades.db"

def inspect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall()
    
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now()
    
    print(f"Current Time (UTC): {now_utc}")
    print(f"Current Time (Local): {now_local}")
    print("-" * 50)
    
    for row in rows:
        pos = dict(row)
        print(f"ID: {pos['id']}")
        print(f"Question: {pos['question']}")
        print(f"Open TS: {pos['open_ts']}")
        print(f"End Date: {pos['end_date']}")
        print(f"Entry Price: {pos['entry_price']}")
        
        # Calculate days_left like the bot does
        days_left = None
        if pos['end_date']:
            try:
                dt = datetime.fromisoformat(str(pos['end_date']).replace('Z', '+00:00'))
                days_left = (dt - now_utc).total_seconds() / 86400
                print(f"Days Left: {days_left:.4f} ({days_left*24:.2f} hours)")
            except Exception as e:
                print(f"Error parsing end_date: {e}")
        
        # Calculate hold_hours like the bot does
        try:
            open_naive = datetime.strptime(pos['open_ts'], '%Y-%m-%d %H:%M:%S')
            hold_hours = (now_local - open_naive).total_seconds() / 3600
            print(f"Hold Hours: {hold_hours:.2f}h")
        except Exception as e:
            print(f"Error calculating hold_hours: {e}")
            
        print("-" * 50)
    
    conn.close()

if __name__ == "__main__":
    inspect()
