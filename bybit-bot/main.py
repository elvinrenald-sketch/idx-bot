"""
Bybit Crypto Algo Bot — Main Orchestrator
Ties together: Scanner → Strategy → Risk → Executor → DB → Telegram → Dashboard
"""
import os
import sys
import json
import time
import asyncio
import logging
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional
from contextlib import asynccontextmanager
import pandas as pd

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from config import (
    BYBIT_API_KEY, BYBIT_API_SECRET, TG_TOKEN, TG_CHAT_ID,
    TIMEFRAMES, PRIMARY_TIMEFRAME, SCAN_INTERVAL_SEC,
    POSITION_CHECK_SEC, MAX_OPEN_POSITIONS, DATA_DIR, WEB_PORT,
    BYBIT_TESTNET, ACCUM_MAX_RANGE_PCT, VOLUME_BREAKOUT_MULT, STOCH_ENTRY_MIN,
    STOCH_ENTRY_MAX, SL_BUFFER_PCT, DEFAULT_RR_RATIO, TRIPLE_SCREEN_ENABLED,
    NEW_LISTING_DAYS, MIN_H4_CANDLES_FOR_STRUCTURE, MIN_D1_CANDLES_FOR_STRUCTURE,
    STOCH_ENTRY_GATE, STOCH_K, STOCH_SMOOTH_K, STOCH_D
)
import db
from scanner import MarketScanner
from strategy import analyze, is_pucuk, is_pump_candle, calc_atr, calc_stochastic
from risk_manager import calculate_leverage, calculate_position_size, calculate_trailing_sl
from executor import BybitExecutor

# ══════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(DATA_DIR, 'bot.log'), encoding='utf-8'),
    ]
)
log = logging.getLogger('main')

# ══════════════════════════════════════════════════════════════
# GLOBAL STATE (for dashboard)
# ══════════════════════════════════════════════════════════════
class WebState:
    def __init__(self):
        self.status = 'STARTING'
        self.scans = 0
        self.last_scan_time = ''
        self.last_scan_ms = 0
        self.equity = 0.0
        self.balance_info = {}
        self.open_positions = []
        self.alpha_coins = []
        self.signals_found = 0
        self.stats = {}
        self.recent_trades = []

WEB = WebState()

# ══════════════════════════════════════════════════════════════
# TELEGRAM — Auto-detect Chat ID
# ══════════════════════════════════════════════════════════════
_active_chat_id: str = TG_CHAT_ID  # Start from env var, update dynamically
_tg_offset: int = 0


async def tg_poll_chat_id(session: aiohttp.ClientSession):
    """Poll Telegram getUpdates to auto-detect chat ID.
    Runs when TG_CHAT_ID env var is empty.
    Once detected, saves it and stops polling.
    """
    global _active_chat_id, _tg_offset
    if _active_chat_id:
        return  # Already have chat_id
    if not TG_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
        resp = await session.get(url, params={'offset': _tg_offset, 'timeout': 1},
                                  timeout=aiohttp.ClientTimeout(total=5))
        data = await resp.json()
        if data.get('ok') and data.get('result'):
            for update in data['result']:
                _tg_offset = update['update_id'] + 1
                msg = update.get('message') or update.get('channel_post', {})
                chat = msg.get('chat', {})
                chat_id = str(chat.get('id', ''))
                if chat_id:
                    _active_chat_id = chat_id
                    log.info(f"✅ Telegram Chat ID detected: {chat_id} "
                             f"({chat.get('first_name', '')} {chat.get('username', '')})")
                    await tg_send_raw(session, chat_id,
                        f"✅ <b>Bybit Alpha Bot Connected!</b>\n"
                        f"💰 Equity: ${WEB.equity:.2f}\n"
                        f"🤖 Bot terhubung dan siap trading!"
                    )
                    break
    except Exception as e:
        log.debug(f"TG poll error: {e}")


async def tg_send_raw(session: aiohttp.ClientSession, chat_id: str, text: str):
    """Send to a specific chat_id directly."""
    if not TG_TOKEN or not chat_id:
        log.warning(f"TG skip: token={bool(TG_TOKEN)} chat_id={bool(chat_id)}")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        resp = await session.post(url, json={
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }, timeout=aiohttp.ClientTimeout(total=10))
        resp_data = await resp.json()
        if resp_data.get('ok'):
            log.info(f"📨 Telegram sent OK to {chat_id}")
        else:
            log.error(f"📨 Telegram API error: {resp_data.get('description', resp_data)}")
    except Exception as e:
        log.error(f"📨 Telegram send failed: {e}")


async def tg_send(session: aiohttp.ClientSession, text: str):
    """Send message to Telegram (uses auto-detected or configured chat_id)."""
    if not TG_TOKEN:
        log.warning("TG: No token configured")
        return
    chat_id = _active_chat_id
    if not chat_id:
        log.warning("TG: No chat_id yet. Send /start to the bot first.")
        return
    log.info(f"📨 TG sending to {chat_id}...")
    await tg_send_raw(session, chat_id, text)


async def tg_signal(session: aiohttp.ClientSession, signal: Dict, sizing: Dict,
                    order_result: Dict):
    """Send entry notification to Telegram."""
    entry = order_result.get('fill_price', signal['entry_price'])
    entry_type = signal.get('signal_type', 'LONG')
    entry_emoji = '📐' if 'TRENDLINE' in entry_type else '🏠'
    retests = signal.get('resistance_retest_count', 0)
    flat_res = signal.get('flat_resistance', 0)
    text = (
        f"🎯 <b>{entry_emoji} {entry_type}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>{signal['symbol']}</b> ({signal['timeframe']})\n"
        f"💰 Entry: <code>{entry:.6f}</code>\n"
        f"🛑 SL: <code>{signal['sl_price']:.6f}</code> ({signal['sl_pct']:.1f}%)\n"
        f"🎯 TP: <code>{signal['tp_price']:.6f}</code> ({signal['tp_pct']:.1f}%)\n"
        f"📐 R:R = 1:{signal['rr_ratio']:.1f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Leverage: {sizing['leverage']}x\n"
        f"📦 Qty: {sizing['qty']}\n"
        f"💵 Margin: ${sizing['margin_required']:.2f}\n"
        f"🎲 Risk: ${sizing['risk_amount']:.4f} ({sizing['risk_pct']:.1f}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Vol: {signal.get('volume_ratio', 1.0)}x avg\n"
        f"🔺 HL: {signal.get('hl_touches', 0)} touches\n"
        f"🏔️ Resistance: {flat_res:.4f} | Retests: {retests}x\n"
        f"📉 Rise: {signal.get('total_rise_pct', 0):.1f}%\n"
        f"🧠 Confidence: {signal.get('confidence', 0)}/100"
    )
    await tg_send(session, text)



async def tg_close(session: aiohttp.ClientSession, pos: Dict, reason: str):
    """Send close notification to Telegram."""
    pnl = pos.get('pnl', 0)
    pnl_pct = pos.get('pnl_pct', 0)
    emoji = '✅' if pnl >= 0 else '❌'
    text = (
        f"{emoji} <b>POSITION CLOSED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 {pos.get('bybit_symbol', '')}\n"
        f"💰 Entry: {pos.get('entry_price', 0):.6f}\n"
        f"💰 Exit: {pos.get('exit_price', 0):.6f}\n"
        f"📊 PnL: ${pnl:.4f} ({pnl_pct:+.2f}%)\n"
        f"📝 Reason: {reason}"
    )
    await tg_send(session, text)


# ══════════════════════════════════════════════════════════════
# MAIN SCAN LOOP
# ══════════════════════════════════════════════════════════════
async def sync_positions_from_bybit(executor: BybitExecutor, session):
    """Sync open positions from Bybit into DB.
    Catches 'orphaned' positions that were opened but not recorded
    (e.g. due to crash after order but before DB insert).
    """
    try:
        bybit_positions = await asyncio.to_thread(executor.get_all_positions)
        db_open = db.get_open_positions()
        db_symbols = {p['bybit_symbol'] for p in db_open}

        synced = 0
        for pos in bybit_positions:
            symbol = pos['symbol']  # e.g. SOLUSDT
            if symbol not in db_symbols:
                # Orphaned position — register in DB
                entry_price = pos['entry_price']
                size = pos['size']
                leverage = pos['leverage']
                sl = pos['stop_loss']
                tp = pos['take_profit']

                # Convert SOLUSDT → SOL/USDT:USDT
                base = symbol.replace('USDT', '')
                ccxt_symbol = f"{base}/USDT:USDT"

                margin = (entry_price * size) / leverage if leverage > 0 else 0

                pos_id = db.open_position(
                    symbol=ccxt_symbol,
                    bybit_symbol=symbol,
                    entry_price=entry_price,
                    qty=size,
                    leverage=leverage,
                    sl_price=sl,
                    tp_price=tp,
                    margin_used=margin,
                    timeframe='synced',
                    alpha_pct=0,
                    volume_ratio=1.0,
                    signal_data=json.dumps({'synced': True, 'source': 'bybit_sync'}),
                )
                log.info(f"🔄 SYNCED orphan position: #{pos_id} {symbol} "
                         f"@ {entry_price:.4f} qty={size} lev={leverage}x")

                await tg_send(session,
                    f"🔄 <b>POSITION SYNCED</b>\n"
                    f"📊 {symbol} (dari Bybit)\n"
                    f"💰 Entry: {entry_price:.4f}\n"
                    f"🛑 SL: {sl:.4f}\n"
                    f"🎯 TP: {tp:.4f}\n"
                    f"📦 Qty: {size} | Lev: {leverage}x\n"
                    f"ℹ️ Posisi ini sudah ada di Bybit tapi belum tercatat"
                )
                synced += 1

        if synced > 0:
            log.info(f"🔄 Synced {synced} orphaned positions from Bybit")
        else:
            log.info(f"🔄 Position sync: {len(bybit_positions)} on Bybit, "
                     f"{len(db_open)} in DB — all matched")

    except Exception as e:
        log.error(f"Position sync error: {e}")


async def scan_loop(scanner: MarketScanner, executor: BybitExecutor):
    """Main scanning loop — runs every SCAN_INTERVAL_SEC."""
    log.info("🚀 Scan loop started")
    already_traded = set()  # Symbols traded this session

    async with aiohttp.ClientSession() as session:
        # Startup notification
        equity = await asyncio.to_thread(executor.get_equity)
        await tg_send(session,
            f"🤖 <b>Bybit Alpha Bot Started</b>\n"
            f"💰 Equity: ${equity:.2f}\n"
            f"⚙️ Testnet: {BYBIT_TESTNET}\n"
            f"📊 Timeframes: {', '.join(TIMEFRAMES)}\n"
            f"🎯 Strategy: Kalimasada v6 Ascending Triangle (LONG)\n"
            f"📅 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )

        # Sync orphaned positions from Bybit
        await sync_positions_from_bybit(executor, session)

        # Mark all open positions as already traded
        for p in db.get_open_positions():
            already_traded.add(p['bybit_symbol'])

        while True:
            try:
                t0 = time.time()
                WEB.status = 'SCANNING'

                # ── Poll Telegram chat ID (until found) ────────
                await tg_poll_chat_id(session)

                # ── Step 1: Get current equity ──────────────────
                equity = await asyncio.to_thread(executor.get_equity)
                balance_info = await asyncio.to_thread(executor.get_balance)
                WEB.equity = equity
                WEB.balance_info = balance_info

                if equity <= 0:
                    log.warning("Zero equity. Waiting...")
                    WEB.status = 'NO_EQUITY'
                    await asyncio.sleep(60)
                    continue

                # ── Step 2: Check how many slots available ──────
                open_count = db.count_open()
                slots = MAX_OPEN_POSITIONS - open_count
                open_symbols = db.get_open_symbols()

                # ── Step 3: ALWAYS scan top coins for watchlist ──────
                all_coins = await asyncio.to_thread(scanner.scan_top_volume)
                WEB.alpha_coins = all_coins

                if slots <= 0:
                    log.info(f"Max positions ({MAX_OPEN_POSITIONS}) reached. Monitoring only.")
                    WEB.status = 'MAX_POSITIONS'
                else:

                    # ── Step 4: Pure PA — analyze() ascending triangle ──
                    signals = []
                    for coin in all_coins:
                        if coin['bybit_symbol'] in open_symbols:
                            continue
                        if coin['bybit_symbol'] in already_traded:
                            continue

                        ohlcv_data = await asyncio.to_thread(
                            scanner.fetch_multi_timeframe, coin['symbol']
                        )

                        # PURE PRICE ACTION: analyze() handles everything
                        # Ascending Triangle: Flat Resistance + Higher Lows
                        # Entry: HL Trendline Touch / Demand 3x Retest
                        # Internal guards: anti-pump candle, slope check
                        for tf in TIMEFRAMES:
                            df = ohlcv_data.get(tf)
                            if df is None or len(df) < 60:
                                continue

                            # ── Stochastic Gate (5,3,3) — Entry ONLY if %K < 50 ──
                            if tf == '15m':
                                # M15: Cek stoch H1 ATAU H4 — salah satu harus < 50
                                h1_df = ohlcv_data.get('1h')
                                h4_df = ohlcv_data.get('4h')
                                stoch_pass = False
                                for htf_label, htf_df in [('H1', h1_df), ('H4', h4_df)]:
                                    if htf_df is not None and len(htf_df) >= 10:
                                        sk, _ = calc_stochastic(htf_df, STOCH_K, STOCH_SMOOTH_K, STOCH_D)
                                        k_val = sk.iloc[-1]
                                        if not pd.isna(k_val) and k_val < STOCH_ENTRY_GATE:
                                            stoch_pass = True
                                            log.info(f"✅ STOCH M15 via {htf_label}: {coin['base']} %K={k_val:.1f} < {STOCH_ENTRY_GATE}")
                                            break
                                if not stoch_pass:
                                    log.info(f"⛔ STOCH_GATE_REJECT M15: {coin['base']} — H1/H4 stoch >= {STOCH_ENTRY_GATE}")
                                    continue
                            else:
                                # H1/H4: Cek stoch di TF sendiri — harus < 50
                                sk, _ = calc_stochastic(df, STOCH_K, STOCH_SMOOTH_K, STOCH_D)
                                k_val = sk.iloc[-1]
                                if pd.isna(k_val) or k_val >= STOCH_ENTRY_GATE:
                                    log.info(f"⛔ STOCH_GATE_REJECT {tf}: {coin['base']} %K={k_val:.1f} >= {STOCH_ENTRY_GATE}")
                                    continue

                            signal = analyze(df, coin['symbol'], tf)
                            if signal:
                                signal['bybit_symbol'] = coin['bybit_symbol']
                                signal['volume_24h'] = coin['volume_24h']
                                signal['market_info'] = coin['market_info']
                                signals.append(signal)
                                break

                        if len(signals) >= slots:
                            break

                    WEB.signals_found = len(signals)

                    # ── Step 5: Execute trades ──────────────────
                    for signal in signals:
                        if slots <= 0:
                            break

                        try:
                            # Calculate leverage
                            leverage = calculate_leverage(signal['atr_pct'])

                            # Calculate position size
                            minfo = signal['market_info']
                            sizing = calculate_position_size(
                                equity=equity,
                                entry_price=signal['entry_price'],
                                sl_price=signal['sl_price'],
                                leverage=leverage,
                                min_qty=minfo['min_qty'],
                                qty_step=minfo['qty_step'],
                            )

                            if not sizing:
                                log.warning(f"Cannot size position for {signal['symbol']}")
                                continue

                            # Execute order
                            result = await asyncio.to_thread(
                                executor.open_long,
                                signal['bybit_symbol'],
                                sizing['qty'],
                                leverage,
                                signal['sl_price'],
                                signal['tp_price'],
                                minfo['price_precision'],
                            )

                            if result and result.get('success'):
                                # Save to DB
                                fill_price = result.get('fill_price', signal['entry_price'])
                                if fill_price <= 0:
                                    fill_price = signal['entry_price']

                                pos_id = db.open_position(
                                    symbol=signal['symbol'],
                                    bybit_symbol=signal['bybit_symbol'],
                                    entry_price=fill_price,
                                    qty=sizing['qty'],
                                    leverage=leverage,
                                    sl_price=signal['sl_price'],
                                    tp_price=signal['tp_price'],
                                    margin_used=sizing['margin_required'],
                                    timeframe=signal['timeframe'],
                                    alpha_pct=0,
                                    volume_ratio=signal.get('volume_ratio', 1.0),
                                    signal_data=json.dumps({
                                        'confidence': signal.get('confidence', 0),
                                        'signal_type': signal.get('signal_type', ''),
                                        'hl_touches': signal.get('hl_touches', 0),
                                        'resistance_retests': signal.get('resistance_retest_count', 0),
                                    }),
                                )

                                already_traded.add(signal['bybit_symbol'])
                                slots -= 1

                                # Telegram notification
                                await tg_signal(session, signal, sizing, result)

                                log.info(f"✅ TRADE EXECUTED: #{pos_id} {signal['bybit_symbol']} "
                                         f"@ {fill_price:.6f}")
                            else:
                                # Order gagal — kirim notif ke Telegram juga
                                err_msg = result.get('error', 'Unknown') if result else 'No result'
                                log.warning(f"Order failed for {signal['symbol']}: {err_msg}")
                                await tg_send(session,
                                    f"⚠️ <b>ORDER FAILED</b>\n"
                                    f"📊 {signal['symbol']} ({signal['timeframe']})\n"
                                    f"❌ {err_msg}\n"
                                    f"💰 Equity: ${WEB.equity:.2f}"
                                )

                        except Exception as trade_err:
                            log.error(f"Trade execution error: {trade_err}")

                # ── Step 6: Log scan ────────────────────────────
                scan_ms = int((time.time() - t0) * 1000)
                WEB.scans += 1
                WEB.last_scan_time = datetime.utcnow().strftime('%H:%M:%S')
                WEB.last_scan_ms = scan_ms
                WEB.stats = db.get_stats()
                WEB.recent_trades = db.get_recent_trades(100)
                WEB.open_positions = db.get_open_positions()
                WEB.status = 'IDLE'

                db.log_scan(
                    total_coins=len(scanner.markets_info),
                    alpha_coins=len(WEB.alpha_coins),
                    signals=WEB.signals_found,
                    scan_time_ms=scan_ms,
                )
                db.log_equity(equity, balance_info.get('available', 0), open_count)

                log.info(f"[SCAN #{WEB.scans}] {scan_ms}ms | "
                         f"Alpha:{len(WEB.alpha_coins)} Signals:{WEB.signals_found} "
                         f"Open:{open_count}/{MAX_OPEN_POSITIONS} "
                         f"Equity:${equity:.2f}")

            except Exception as scan_err:
                log.error(f"Scan loop error: {scan_err}", exc_info=True)
                WEB.status = 'ERROR'

            await asyncio.sleep(SCAN_INTERVAL_SEC)


# ══════════════════════════════════════════════════════════════
# POSITION MONITOR LOOP
# ══════════════════════════════════════════════════════════════
async def monitor_loop(executor: BybitExecutor):
    """Monitor open positions for trailing stop updates and closed positions."""
    log.info("👀 Position monitor started")
    await asyncio.sleep(10)  # Wait for first scan

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                open_positions = db.get_open_positions()

                for pos in open_positions:
                    try:
                        # Get live position from Bybit
                        live = await asyncio.to_thread(
                            executor.get_position, pos['bybit_symbol']
                        )

                        if live is None:
                            # Position no longer exists on Bybit (hit SL or TP)
                            # Determine reason from last known data
                            mark = pos.get('sl_price', pos['entry_price'])

                            # Check which triggered
                            reason = 'CLOSED_BY_EXCHANGE'
                            # Try to get the actual close info
                            if pos['tp_price'] and pos['entry_price']:
                                # We don't know exact price, estimate
                                if pos['sl_price'] > 0:
                                    reason = 'SL_OR_TP_HIT'

                            # Get last trade for this symbol to find exit price
                            exit_price = await asyncio.to_thread(
                                _get_last_close_price, executor, pos['bybit_symbol']
                            )
                            if exit_price <= 0:
                                exit_price = pos['entry_price']  # Fallback

                            closed = db.close_position(pos['id'], exit_price, reason)
                            if closed:
                                await tg_close(session, closed, reason)
                            continue

                        # Position still open — check for trailing stop
                        current_price = live['mark_price']
                        if current_price > 0 and pos['entry_price'] > 0:
                            new_sl = calculate_trailing_sl(
                                entry_price=pos['entry_price'],
                                current_price=current_price,
                                original_sl=pos['sl_price'],
                                current_sl=live.get('stop_loss', pos['sl_price']),
                            )

                            if new_sl and new_sl > live.get('stop_loss', 0):
                                # Update SL on Bybit (server-side)
                                success = await asyncio.to_thread(
                                    executor.update_sl_tp,
                                    pos['bybit_symbol'],
                                    sl_price=new_sl,
                                )
                                if success:
                                    db.update_sl(pos['id'], new_sl)
                                    await tg_send(session,
                                        f"📈 <b>TRAILING SL</b>\n"
                                        f"{pos['bybit_symbol']}: SL → {new_sl:.6f}"
                                    )

                    except Exception as pos_err:
                        log.error(f"Monitor error for #{pos['id']}: {pos_err}")

            except Exception as mon_err:
                log.error(f"Monitor loop error: {mon_err}")

            await asyncio.sleep(POSITION_CHECK_SEC)


def _get_last_close_price(executor: BybitExecutor, bybit_symbol: str) -> float:
    """Try to get the fill price of the last closed trade."""
    try:
        result = executor.session.get_closed_pnl(
            category="linear",
            symbol=bybit_symbol,
            limit=1,
        )
        if result['retCode'] == 0 and result['result']['list']:
            return float(result['result']['list'][0].get('avgExitPrice', 0))
    except Exception:
        pass
    return 0.0


# ══════════════════════════════════════════════════════════════
# FASTAPI DASHBOARD
# ══════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    log.info("=" * 60)
    log.info("🤖 BYBIT ALPHA BOT — Kalimasada v6 Ascending Triangle")
    log.info("=" * 60)

    # Validate config
    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        log.error("❌ BYBIT_API_KEY and BYBIT_API_SECRET required!")
        log.error("   Set them as environment variables and restart.")
        # Don't exit — dashboard still works for config debugging
        WEB.status = 'NO_API_KEY'
        yield
        return

    # Init DB
    db.init_db()

    # Init scanner and executor
    scanner = MarketScanner()
    executor = BybitExecutor()

    # Load markets
    try:
        await asyncio.to_thread(scanner.load_markets)
    except Exception as e:
        log.error(f"Failed to load markets: {e}")
        WEB.status = 'MARKET_LOAD_FAILED'
        yield
        return

    # Get initial equity
    equity = await asyncio.to_thread(executor.get_equity)
    log.info(f"💰 Starting equity: ${equity:.2f}")
    WEB.equity = equity

    # Start background tasks
    scan_task = asyncio.create_task(scan_loop(scanner, executor))
    monitor_task = asyncio.create_task(monitor_loop(executor))

    yield

    # Cleanup
    scan_task.cancel()
    monitor_task.cancel()
    scanner.close()
    log.info("Bot shutdown complete")


app = FastAPI(title="Bybit Alpha Bot", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/state")
async def api_state():
    return JSONResponse({
        'status': WEB.status,
        'scans': WEB.scans,
        'last_scan_time': WEB.last_scan_time,
        'last_scan_ms': WEB.last_scan_ms,
        'equity': WEB.equity,
        'balance': WEB.balance_info,
        'stats': WEB.stats,
        'open_positions': WEB.open_positions,
        'alpha_coins': WEB.alpha_coins[:30],
        'signals_found': WEB.signals_found,
        'recent_trades': WEB.recent_trades,
        'testnet': BYBIT_TESTNET,
        'max_positions': MAX_OPEN_POSITIONS,
        'timeframes': TIMEFRAMES,
    })


@app.get("/health")
async def health():
    return {"status": "ok", "scans": WEB.scans}


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=WEB_PORT,
        log_level="info",
    )
