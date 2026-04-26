"""
Kalimasada v6 — ASCENDING TRENDLINE HL + DEMAND 3X RETEST BACKTEST
Menggunakan analyze() LANGSUNG dari strategy.py

Pattern:
  Price
    |        /\      /\
    |       /  \    /  \     /
    |      /    \  /    \   /
    |     /      \/      \ /  <- HL#2 (ENTRY A)
    |    /        HL#1
    |   /
    |--/-- Demand Zone --------
    | ^    ^          ^
    | 1st  2nd        3rd retest (ENTRY B)

ENTRY A: Di HL ke-2 pada ascending trendline yang NAIK
ENTRY B: Di demand zone saat retest ke-3
Backtest: Januari 2026 sampai hari ini
"""
import os, sys, time, ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy import (
    analyze, is_pucuk, is_bullish_structure,
    is_pump_candle, calc_atr
)

# ══════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════
INITIAL_CAPITAL = 3.50
RISK_PCT = 3.0
LEVERAGE = 10
FEE_PCT = 0.075

# BACKTEST DARI JANUARI 2026
since_dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
since_ms = int(since_dt.timestamp() * 1000)

COINS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'LINK/USDT',
    'NEAR/USDT', 'SUI/USDT', 'APT/USDT', 'ARB/USDT', 'OP/USDT',
    'FIL/USDT', 'LTC/USDT', 'BCH/USDT', 'UNI/USDT', 'AAVE/USDT',
    'ATOM/USDT', 'ALGO/USDT', 'SAND/USDT', 'MANA/USDT',
    'GALA/USDT', 'IMX/USDT', 'LDO/USDT', 'CRV/USDT',
    'PEPE/USDT', 'WIF/USDT', 'BONK/USDT', 'FLOKI/USDT', 'SHIB/USDT',
    'TIA/USDT', 'SEI/USDT', 'INJ/USDT', 'ONDO/USDT', 'PENDLE/USDT',
    'RENDER/USDT', 'FET/USDT', 'JASMY/USDT', 'CHZ/USDT',
    'COMP/USDT', 'SNX/USDT', 'BLUR/USDT',
    'RUNE/USDT', 'ICP/USDT', 'HBAR/USDT', 'VET/USDT',
    'TRX/USDT', 'ETC/USDT',
    'TAO/USDT', 'WLD/USDT', 'STRK/USDT',
    'ARKM/USDT', 'SUPER/USDT', 'CORE/USDT', 'KAS/USDT',
    'FARTCOIN/USDT', 'BNB/USDT', 'POL/USDT', 'IP/USDT',
    'DASH/USDT', 'ZEC/USDT',
]

# ══════════════════════════════════════════════════════════════
# EXCHANGE
# ══════════════════════════════════════════════════════════════
def try_exchanges():
    for name, cls in [('gate', ccxt.gateio), ('kucoin', ccxt.kucoin),
                      ('mexc', ccxt.mexc), ('bitget', ccxt.bitget),
                      ('bybit', ccxt.bybit), ('binance', ccxt.binance)]:
        try:
            ex = cls({'enableRateLimit': True})
            ex.fetch_ohlcv('BTC/USDT', '1h', limit=5)
            print(f"OK Terhubung ke {name.upper()}")
            return ex
        except Exception as e:
            print(f"X {name}: {str(e)[:50]}")
    return None

def fetch_ohlcv(ex, sym, tf, since, batches=8):
    """Fetch with more batches to cover Jan-Apr 2026"""
    all_d = []
    cur = since
    for _ in range(batches):
        try:
            d = ex.fetch_ohlcv(sym, tf, since=cur, limit=500)
            if not d: break
            all_d.extend(d)
            if len(d) < 500: break
            cur = d[-1][0] + 1
            time.sleep(0.08)
        except: break
    if not all_d: return None
    df = pd.DataFrame(all_d, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df.drop_duplicates(subset='timestamp').reset_index(drop=True)

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
print("=" * 65)
print("  KALIMASADA v6 - ASCENDING TRENDLINE + DEMAND 3X RETEST")
print("=" * 65)
print(f"   Entry A       : HL#2+ pada ascending trendline yang NAIK")
print(f"   Entry B       : Demand zone retest ke-3")
print(f"   Slope         : Trendline HARUS naik (slope positif)")
print(f"   Reject        : Koin sudah pump >20%")
print(f"   Periode       : Januari 2026 -> Hari ini")
print(f"   Modal Awal    : ${INITIAL_CAPITAL:.2f}")
print(f"   Risk/Trade    : {RISK_PCT}%")
print(f"   Leverage      : {LEVERAGE}x")
print(f"   Uses          : strategy.py analyze() (SAME AS LIVE)")
print("=" * 65)

exchange = try_exchanges()
if not exchange:
    print("X Semua exchange diblokir"); sys.exit(1)

# Download data
historical = {}
d1_since = since_ms - (86400000 * 180)  # D1 dari 6 bulan sebelumnya
h4_since = since_ms - (86400000 * 90)
print(f"\n   Downloading {len(COINS)} koin (Jan 2026 - today)...")
for i, sym in enumerate(COINS):
    try:
        h1 = fetch_ohlcv(exchange, sym, '1h', since_ms)
        h4 = fetch_ohlcv(exchange, sym, '4h', h4_since)
        d1 = fetch_ohlcv(exchange, sym, '1d', d1_since)
        if h1 is not None and len(h1) > 60:
            historical[sym] = {'1h': h1, '4h': h4, '1d': d1}
            print(f"   [{i+1:02d}/{len(COINS)}] {sym:18s} "
                  f"H1={len(h1)} H4={len(h4) if h4 is not None else 0} "
                  f"D1={len(d1) if d1 is not None else 0}")
        time.sleep(0.05)
    except:
        pass

print(f"\n   {len(historical)} koin siap.\n")

# ══════════════════════════════════════════════════════════════
# WALK-FORWARD
# ══════════════════════════════════════════════════════════════
equity = INITIAL_CAPITAL
peak = INITIAL_CAPITAL
max_dd = 0.0
trades = []
rejected = {'pucuk': 0, 'no_signal': 0, 'total_scanned': 0}
eq_curve = [{'date': since_dt, 'equity': equity, 'event': 'START'}]

print("   Walk-forward v6 strategy...\n")

for sym, data in historical.items():
    h1 = data['1h']
    h4 = data.get('4h')
    d1 = data.get('1d')

    already_traded = False  # 1 trade per koin saja

    # === SCAN H1 ===
    step = 4
    for start in range(80, len(h1) - 10, step):
        df_slice = h1.iloc[:start+1].copy().reset_index(drop=True)
        curr_ts = h1['timestamp'].iloc[start]
        trade_day = curr_ts.strftime('%Y-%m-%d')
        rejected['total_scanned'] += 1

        if already_traded:
            continue

        # Pucuk check H4/D1
        if d1 is not None and len(d1) > 20:
            d1_s = d1[d1['timestamp'] <= curr_ts].tail(60)
            if len(d1_s) > 20 and is_pucuk(d1_s):
                rejected['pucuk'] += 1
                continue

        if is_pucuk(df_slice):
            rejected['pucuk'] += 1
            continue

        signal = analyze(df_slice, sym, '1h')

        if not signal:
            rejected['no_signal'] += 1
            continue

        entry_price = signal['entry_price']
        sl_price = signal['sl_price']
        tp_price = signal['tp_price']

        future = h1.iloc[start+1 : start+120]
        outcome = None
        for _, fc in future.iterrows():
            if fc['low'] <= sl_price:
                outcome = 'LOSS'; break
            if fc['high'] >= tp_price:
                outcome = 'WIN'; break

        if not outcome:
            continue

        risk_amt = equity * (RISK_PCT / 100)
        position_size = risk_amt * LEVERAGE
        fee = position_size * FEE_PCT / 100 * 2
        sl_dist_pct = abs(entry_price - sl_price) / entry_price
        tp_dist_pct = abs(tp_price - entry_price) / entry_price

        if outcome == 'WIN':
            pnl = (position_size * tp_dist_pct) - fee
        else:
            pnl = -(position_size * sl_dist_pct) - fee

        equity += pnl
        if equity > peak: peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd: max_dd = dd
        if equity <= 0: equity = 0; break

        already_traded = True
        trades.append({
            'date': curr_ts, 'symbol': sym, 'tf': 'H1',
            'type': outcome, 'signal_type': signal.get('signal_type', ''),
            'entry': entry_price, 'sl': sl_price, 'tp': tp_price,
            'pnl': pnl, 'fee': fee, 'equity_after': equity,
            'total_rise': signal.get('total_rise_pct', 0),
            'demand_retests': signal.get('demand_retest_count', 0),
            'hl_count': signal.get('hl_touches', 0),
        })
        eq_curve.append({'date': curr_ts, 'equity': equity,
                         'event': f'{outcome} {signal.get("signal_type","")} {sym} H1'})

    # === SCAN H4 (hanya dari Jan 2026) ===
    if h4 is not None and len(h4) > 60 and not already_traded:
        # Filter: hanya scan H4 dari Januari 2026
        h4_jan = h4[h4['timestamp'] >= pd.Timestamp('2026-01-01')].reset_index(drop=True)
        if len(h4_jan) < 40:
            continue
        for start in range(40, len(h4_jan) - 5):
            if already_traded:
                break
            h4_slice = h4_jan.iloc[:start+1].copy().reset_index(drop=True)
            curr_ts = h4_jan['timestamp'].iloc[start]
            trade_day = curr_ts.strftime('%Y-%m-%d')
            rejected['total_scanned'] += 1

            if d1 is not None and len(d1) > 20:
                d1_s = d1[d1['timestamp'] <= curr_ts].tail(60)
                if len(d1_s) > 20 and is_pucuk(d1_s):
                    rejected['pucuk'] += 1
                    continue

            if is_pucuk(h4_slice):
                rejected['pucuk'] += 1
                continue

            signal = analyze(h4_slice, sym, '4h')

            if not signal:
                rejected['no_signal'] += 1
                continue

            entry_price = signal['entry_price']
            sl_price = signal['sl_price']
            tp_price = signal['tp_price']

            future = h4.iloc[start+1 : start+60]
            outcome = None
            for _, fc in future.iterrows():
                if fc['low'] <= sl_price:
                    outcome = 'LOSS'; break
                if fc['high'] >= tp_price:
                    outcome = 'WIN'; break

            if not outcome:
                continue

            risk_amt = equity * (RISK_PCT / 100)
            position_size = risk_amt * LEVERAGE
            fee = position_size * FEE_PCT / 100 * 2
            sl_dist_pct = abs(entry_price - sl_price) / entry_price
            tp_dist_pct = abs(tp_price - entry_price) / entry_price

            if outcome == 'WIN':
                pnl = (position_size * tp_dist_pct) - fee
            else:
                pnl = -(position_size * sl_dist_pct) - fee

            equity += pnl
            if equity > peak: peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd: max_dd = dd
            if equity <= 0: equity = 0; break

            already_traded = True
            trades.append({
                'date': curr_ts, 'symbol': sym, 'tf': 'H4',
                'type': outcome, 'signal_type': signal.get('signal_type', ''),
                'entry': entry_price, 'sl': sl_price, 'tp': tp_price,
                'pnl': pnl, 'fee': fee, 'equity_after': equity,
                'total_rise': signal.get('total_rise_pct', 0),
                'demand_retests': signal.get('demand_retest_count', 0),
                'hl_count': signal.get('hl_touches', 0),
            })
            eq_curve.append({'date': curr_ts, 'equity': equity,
                             'event': f'{outcome} {signal.get("signal_type","")} {sym} H4'})

# ══════════════════════════════════════════════════════════════
# RESULTS
# ══════════════════════════════════════════════════════════════
wins = [t for t in trades if t['type'] == 'WIN']
losses = [t for t in trades if t['type'] == 'LOSS']
wr = len(wins) / len(trades) * 100 if trades else 0
net_pct = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
total_fees = sum(t['fee'] for t in trades)

gross_profit = sum(t['pnl'] for t in wins) if wins else 0
gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 1
pf = gross_profit / gross_loss if gross_loss > 0 else 0

hl_touch = [t for t in trades if 'HL_TRENDLINE' in t.get('signal_type', '')]
demand_3x = [t for t in trades if 'DEMAND_3X' in t.get('signal_type', '')]

print("\n" + "=" * 65)
print("  HASIL KALIMASADA v6 - ASCENDING TRENDLINE + DEMAND 3X")
print("=" * 65)
print(f"  Modal Awal       : ${INITIAL_CAPITAL:.2f}")
print(f"  Modal Akhir      : ${equity:.4f}")
print(f"  Net Profit       : ${equity - INITIAL_CAPITAL:.4f} ({net_pct:+.1f}%)")
print(f"  Max Drawdown     : {max_dd:.1f}%")
print(f"  Total Fees       : ${total_fees:.4f}")
print(f"  Profit Factor    : {pf:.2f}")
print(f"  ---")
print(f"  Total Trades     : {len(trades)}")
print(f"  Win Rate         : {wr:.1f}%")
print(f"  ---")
print(f"  Signal Types:")
print(f"    HL_TRENDLINE_TOUCH : {len(hl_touch)} ({sum(1 for t in hl_touch if t['type']=='WIN')}W / {sum(1 for t in hl_touch if t['type']=='LOSS')}L)")
print(f"    DEMAND_3X_RETEST   : {len(demand_3x)} ({sum(1 for t in demand_3x if t['type']=='WIN')}W / {sum(1 for t in demand_3x if t['type']=='LOSS')}L)")
print(f"  ---")
print(f"  Filter Stats:")
print(f"    Scanned        : {rejected['total_scanned']}")
print(f"    PUCUK rejected : {rejected['pucuk']}")
print(f"    No signal      : {rejected['no_signal']}")
if wins:
    print(f"  Avg WIN          : +${sum(t['pnl'] for t in wins)/len(wins):.4f}")
if losses:
    print(f"  Avg LOSS         : -${abs(sum(t['pnl'] for t in losses)/len(losses)):.4f}")
if trades:
    ev = sum(t['pnl'] for t in trades) / len(trades)
    print(f"  Expected Value   : ${ev:.4f}/trade")

# Validasi ZEC/DASH
zec_t = [t for t in trades if 'ZEC' in t['symbol']]
dash_t = [t for t in trades if 'DASH' in t['symbol']]
print(f"\n  VALIDASI:")
print(f"    ZEC trades     : {len(zec_t)} {'!! HARUS 0' if zec_t else 'OK filtered'}")
print(f"    DASH trades    : {len(dash_t)} {'OK found setup' if dash_t else 'No setup (belum terbentuk)'}")

# Equity Curve
print(f"\n  Equity Curve:")
for ec in eq_curve:
    bar_len = max(1, int((ec['equity'] / max(INITIAL_CAPITAL, 0.01)) * 20))
    bar = "|" * min(bar_len, 60)
    dt_str = ec['date'].strftime('%m-%d') if hasattr(ec['date'], 'strftime') else str(ec['date'])[:5]
    print(f"    {dt_str} ${ec['equity']:8.4f} {bar} {ec['event']}")

# Trade Log
if trades:
    print(f"\n  Trade Log:")
    print(f"  {'#':>3} {'Date':8} {'TF':3} {'Coin':10} {'Type':22} {'W/L':3} {'Entry':>10} {'SL':>10} {'TP':>10} {'PnL':>10} {'Rise':>5} {'HL':>3} {'DmR':>3}")
    for i, t in enumerate(trades, 1):
        dt = t['date'].strftime('%m-%d')
        sym = t['symbol'].replace('/USDT', '')[:8]
        icon = "W" if t['type'] == 'WIN' else "L"
        pnl_s = f"+${t['pnl']:.3f}" if t['pnl'] > 0 else f"-${abs(t['pnl']):.3f}"
        sig = t.get('signal_type', '')[:20]
        rise = t.get('total_rise', 0)
        hl = t.get('hl_count', 0)
        dmr = t.get('demand_retests', 0)
        tf = t.get('tf', 'H1')
        print(f"  {i:>3} {dt:8} {tf:3} {sym:10} {sig:22} {icon:3} ${t['entry']:9.4f} ${t['sl']:9.4f} ${t['tp']:9.4f} {pnl_s:>10} {rise:4.1f}% {hl:>3} {dmr:>3}")
else:
    print("\n  0 trades - strategi sangat selektif (menghindari bad entries)")

print(f"\n{'='*65}")
print(f"  PERBANDINGAN:")
print(f"  {'Strategi':<36} {'WR':>6} {'Net%':>8} {'MaxDD':>7}")
print(f"  {'_'*36} {'_'*6} {'_'*8} {'_'*7}")
print(f"  {'v1 Pullback':<36} {'36.4%':>6} {'-23.2%':>8} {'64.6%':>7}")
print(f"  {'v2 Ketat':<36} {'0.0%':>6} {'-15.0%':>8} {'15.0%':>7}")
print(f"  {'v3 Bidirectional':<36} {'18.2%':>6} {'-60.9%':>8} {'60.9%':>7}")
print(f"  {'v4 Momentum EMA':<36} {'36.1%':>6} {'-24.7%':>8} {'69.8%':>7}")
print(f"  {'v5 Ascending Triangle (Mar-Apr)':<36} {'0.0%':>6} {'-2.6%':>8} {'2.6%':>7}")
print(f"  {'v6 HL Trendline+Demand3x (Jan-Apr)':<36} {f'{wr:.1f}%':>6} {f'{net_pct:+.1f}%':>8} {f'{max_dd:.1f}%':>7}")
print(f"{'='*65}")
