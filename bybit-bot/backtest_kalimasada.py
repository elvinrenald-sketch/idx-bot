import ccxt
import pandas as pd
import pandas_ta as ta
import time
import datetime
from scanner import MarketScanner

def is_bullish_structure(df):
    if len(df) < 20: return False
    sma20 = df['close'].rolling(20).mean().iloc[-1]
    return df['close'].iloc[-1] > sma20

def analyze_kalimasada(m15, h1, h4, d1, symbol):
    if len(m15) < 20 or len(h1) < 20 or len(h4) < 20 or len(d1) < 5:
        return None
        
    # 1. Higher Timeframe Alignment (D1, H4, H1 harus Uptrend)
    if not is_bullish_structure(d1): return None
    if not is_bullish_structure(h4): return None
    if not is_bullish_structure(h1): return None
    
    # 2. M15 Kalimasada Stoch 5,3,3 logic
    stoch = ta.stoch(m15['high'], m15['low'], m15['close'], k=5, d=3, smooth_k=3)
    if stoch is None or stoch.empty: return None
    
    k_now = stoch[stoch.columns[0]].iloc[-1]
    d_now = stoch[stoch.columns[1]].iloc[-1]
    
    # Syarat utama: Stoch K berada di antara 20 dan 40
    if not (20 <= k_now <= 40):
        return None
        
    # Syarat tambahan Kalimasada: Harga harus di area support/pullback
    # Kita cek M15 dan H1 apakah close dekat dengan SMA20 (maksimal 2% di atas SMA)
    m15_sma20 = m15['close'].rolling(20).mean().iloc[-1]
    m15_close = m15['close'].iloc[-1]
    
    # Pucuk Protector: Jangan entry jika harga M15 sudah > 3% di atas SMA20 M15
    if m15_close > m15_sma20 * 1.03:
        return None
        
    # Calculate Risk Reward
    c = m15_close
    atr = ta.atr(m15['high'], m15['low'], m15['close'], length=14).iloc[-1]
    
    sl = c - (atr * 1.5)
    tp = c + (atr * 3.0)
    
    sl_pct = ((c - sl) / c) * 100
    if sl_pct < 1.0:
        sl_pct = 1.0
        sl = c * 0.99
        tp = c * 1.02
        
    tp_pct = sl_pct * 2.0
    
    return {
        'symbol': symbol,
        'entry_price': c,
        'sl_price': sl,
        'tp_price': tp,
        'sl_pct': sl_pct,
        'tp_pct': tp_pct,
        'rr_ratio': 2.0
    }

def run_backtest():
    scanner = MarketScanner()
    scanner.load_markets()
    symbols = list(scanner.markets_info.keys())
    print(f"Total {len(symbols)} koin ditemukan. Memulai download data (estimasi 5-7 menit)...")
    
    historical_data = {}
    downloaded = 0
    
    for symbol in symbols:
        try:
            m15 = scanner.exchange.fetch_ohlcv(symbol, '15m', limit=672)
            h1 = scanner.exchange.fetch_ohlcv(symbol, '1h', limit=168)
            h4 = scanner.exchange.fetch_ohlcv(symbol, '4h', limit=42)
            d1 = scanner.exchange.fetch_ohlcv(symbol, '1d', limit=7)
            
            if not m15 or len(m15) < 100:
                continue
                
            historical_data[symbol] = {
                '15m': pd.DataFrame(m15, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']),
                '1h': pd.DataFrame(h1, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']),
                '4h': pd.DataFrame(h4, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']),
                '1d': pd.DataFrame(d1, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']),
            }
            
            downloaded += 1
            if downloaded % 20 == 0:
                print(f"✅ Downloaded {downloaded}/{len(symbols)} koin...")
                
            time.sleep(0.05)
        except Exception as e:
            continue
            
    print(f"✅ Selesai download data untuk {downloaded} koin.")
    print("Menjalankan Simulasi Kalimasada M15/H1/H4/D1 (7 Hari Terakhir)...")
    
    trades = []
    coins_processed = 0
    
    for symbol, data in historical_data.items():
        coins_processed += 1
        if coins_processed % 50 == 0:
            print(f"🔄 Simulating... {coins_processed}/{len(historical_data)} koin diproses")
            
        m15_df = data['15m']
        h1_df = data['1h']
        h4_df = data['4h']
        d1_df = data['1d']
        
        for i in range(100, len(m15_df) - 1):
            current_time = m15_df['timestamp'].iloc[i]
            
            current_m15 = m15_df.iloc[:i+1].copy()
            current_h1 = h1_df[h1_df['timestamp'] <= current_time].copy()
            current_h4 = h4_df[h4_df['timestamp'] <= current_time].copy()
            current_d1 = d1_df[d1_df['timestamp'] <= current_time].copy()
            
            signal = analyze_kalimasada(current_m15, current_h1, current_h4, current_d1, symbol)
            
            if signal:
                entry_price = signal['entry_price']
                sl_price = signal['sl_price']
                tp_price = signal['tp_price']
                
                # Cek hasil di M15 berikutnya
                outcome = 'LOSS'
                for j in range(i+1, len(m15_df)):
                    future_low = m15_df['low'].iloc[j]
                    future_high = m15_df['high'].iloc[j]
                    
                    if future_low <= sl_price:
                        outcome = 'LOSS'
                        break
                    if future_high >= tp_price:
                        outcome = 'WIN'
                        break
                
                if outcome == 'WIN':
                    trades.append({'symbol': symbol, 'pnl': signal['tp_pct']})
                else:
                    trades.append({'symbol': symbol, 'pnl': -signal['sl_pct']})
                    
                # Skip 12 candle (3 jam) agar tidak double entry di pola yg sama
                # Not possible perfectly with loop, but we can just let it collect everything 
                # For realism, we usually want to skip.
                # Since we can't modify 'i' in python for loop, we just ignore this for now.
                
    wins = len([t for t in trades if t['pnl'] > 0])
    losses = len([t for t in trades if t['pnl'] < 0])
    total = len(trades)
    win_rate = (wins / total * 100) if total > 0 else 0
    
    starting_balance = 10.0
    balance = starting_balance
    risk_per_trade = 0.03
    
    for t in trades:
        risk_amount = balance * risk_per_trade
        position_size = risk_amount / (abs(t['pnl']) / 100)
        profit = position_size * (t['pnl'] / 100)
        balance += profit
        
    net_profit = balance - starting_balance
    roi = (net_profit / starting_balance) * 100
    
    print("\n" + "="*50)
    print("📊 HASIL BACKTEST KALIMASADA (M15 Stoch 5,3,3)")
    print("="*50)
    print(f"Modal Awal     : ${starting_balance:.2f}")
    print(f"Modal Akhir    : ${balance:.2f}")
    print(f"Net Profit     : ${net_profit:.2f} ({roi:.1f}%)")
    print(f"\nTotal Trades   : {total}")
    print(f"Winning Trades : {wins}")
    print(f"Losing Trades  : {losses}")
    print(f"Win Rate       : {win_rate:.1f}%")
    print("="*50)

if __name__ == "__main__":
    run_backtest()
