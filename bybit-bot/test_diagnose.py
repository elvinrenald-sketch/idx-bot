import sys, json, os, asyncio
os.environ['BYBIT_API_KEY'] = 'fake'
os.environ['BYBIT_API_SECRET'] = 'fake'
from main import diagnose_analyze
import ccxt
import pandas as pd

ex = ccxt.bybit({'options': {'defaultType': 'swap'}})
for coin in ['BSB/USDT:USDT', 'BIO/USDT:USDT', 'APE/USDT:USDT', 'ORCA/USDT:USDT', 'FARTCOIN/USDT:USDT', 'CL/USDT:USDT']:
    for tf in ['1h', '4h']:
        try:
            ohlcv = ex.fetch_ohlcv(coin, tf, limit=150)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            reason = diagnose_analyze(df, coin, tf)
            print(f"{coin:18s} {tf:3s}: {reason}")
        except Exception as e:
            print(f"{coin:18s} {tf:3s}: ERROR {str(e)}")
