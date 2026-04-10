import sqlite3
from datetime import datetime, timezone

DB_PATH = "/Users/oliveaprilia/polymarket-scanner/journal/trades.db"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id, open_ts, end_date FROM positions WHERE status='OPEN'").fetchall()

now = datetime.now(timezone.utc)
for row in rows:
    pos = dict(row)
    open_ts = pos['open_ts']
    end_date = pos['end_date']
    days_left = None
    if end_date:
        try:
            dt = datetime.fromisoformat(str(end_date).replace('Z', '+00:00'))
            days_left = (dt - now).total_seconds() / 86400
        except Exception as e:
            print("Err parsing end_date:", e)
    open_dt = datetime.strptime(open_ts, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    hold_hours = (now - open_dt).total_seconds() / 3600
    print(f"ID={pos['id']} open_ts={open_ts} hold={hold_hours:.2f}h end_date={end_date} days_left={days_left}")
