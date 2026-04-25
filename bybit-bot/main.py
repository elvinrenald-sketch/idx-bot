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
    NEW_LISTING_DAYS, MIN_H4_CANDLES_FOR_STRUCTURE, MIN_D1_CANDLES_FOR_STRUCTURE
)
import db
from scanner import MarketScanner
from strategy import analyze, is_pucuk, is_pump_candle, calc_atr
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
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        await session.post(url, json={
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }, timeout=aiohttp.ClientTimeout(total=10))
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")


async def tg_send(session: aiohttp.ClientSession, text: str):
    """Send message to Telegram (uses auto-detected or configured chat_id)."""
    if not TG_TOKEN:
        return
    chat_id = _active_chat_id
    if not chat_id:
        log.debug("TG: No chat_id yet. Send /start to the bot first.")
        return
    await tg_send_raw(session, chat_id, text)


async def tg_signal(session: aiohttp.ClientSession, signal: Dict, sizing: Dict,
                    order_result: Dict):
    """Send entry notification to Telegram."""
    entry = order_result.get('fill_price', signal['entry_price'])
    entry_type = signal.get('signal_type', 'LONG')
    entry_emoji = '📐' if 'TRENDLINE' in entry_type else '🏠'
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
        f"📊 Vol: {signal['volume_ratio']}x avg\n"
        f"📈 Stoch: {signal['stoch_k']:.0f}/{signal['stoch_d']:.0f} ({signal['stoch_signal']})\n"
        f"🔺 HL: {signal['hl_touches']} touches\n"
        f"⭐ Alpha: +{signal.get('alpha', 0):.1f}% vs BTC\n"
        f"🧬 Decoupled: {'✅' if signal.get('is_decoupled') else '❌'} (Corr: {signal.get('correlation', 1)})\n"
        f"🔥 Vol Alpha: {'✅' if signal.get('is_volume_alpha') else '❌'} ({signal.get('vol_ratio', 1)}x)\n"
        f"🧠 Confidence: {signal['confidence']}/100"
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

                if slots <= 0:
                    log.info(f"Max positions ({MAX_OPEN_POSITIONS}) reached. Monitoring only.")
                    WEB.status = 'MAX_POSITIONS'
                else:
                    # ── Step 3: Scan Alpha + Volume coins (v6 style) ─
                    # Alpha: koin yang sudah outperform BTC
                    # Volume: top 60 by volume (mirip v6 backtest 63 koin)
                    # Merge keduanya — ascending triangle bisa ada di kedua grup
                    alpha_coins = await asyncio.to_thread(scanner.scan_for_alpha)
                    volume_coins = await asyncio.to_thread(scanner.scan_top_volume)

                    # Deduplicate: gabung alpha + volume, prioritas alpha
                    seen = set()
                    all_coins = []
                    for coin in alpha_coins:
                        seen.add(coin['bybit_symbol'])
                        all_coins.append(coin)
                    for coin in volume_coins:
                        if coin['bybit_symbol'] not in seen:
                            seen.add(coin['bybit_symbol'])
                            all_coins.append(coin)

                    WEB.alpha_coins = all_coins
                    log.info(f"Combined scan: {len(alpha_coins)} alpha + {len(volume_coins)} vol → {len(all_coins)} unique coins")

                    # ── Step 4: Deep analysis on ALL coins ─────────
                    signals = []
                    for coin in all_coins:
                        if coin['bybit_symbol'] in open_symbols:
                            continue  # Already have position
                        if coin['bybit_symbol'] in already_traded:
                            continue  # Already traded this session

                        # Fetch OHLCV for all timeframes
                        ohlcv_data = await asyncio.to_thread(
                            scanner.fetch_multi_timeframe, coin['symbol']
                        )

                        # Run strategy on each timeframe
                        for tf in TIMEFRAMES:
                            df = ohlcv_data.get(tf)
                            if df is None:
                                continue

                        # ── KALIMASADA v7 PURE PRICE ACTION ──
                        # Strategy sekarang handle semuanya:
                        # Flat Resistance + Ascending HL + Demand 3x + Pump Guard
                        # Main cukup pre-filter pucuk di H4/D1 untuk efisiensi
                        for tf in TIMEFRAMES:
                            df = ohlcv_data.get(tf)
                            if df is None or len(df) < 60:
                                continue

                            # Skip M15 kecuali new listing
                            if tf == '15m' and not coin.get('is_new_listing', False):
                                continue

                            # Pre-filter PUCUK cepat di D1/H4 sebelum analyze()
                            d1_df = ohlcv_data.get('1d')
                            h4_df = ohlcv_data.get('4h')

                            if d1_df is not None and len(d1_df) > 20:
                                if is_pucuk(d1_df):
                                    log.info(f"🚫 PUCUK D1 REJECT {coin['base']} {tf}")
                                    continue

                            if h4_df is not None and len(h4_df) > 20 and tf in ('15m', '1h'):
                                if is_pucuk(h4_df):
                                    log.info(f"🚫 PUCUK H4 REJECT {coin['base']} {tf}")
                                    continue

                            # PURE PRICE ACTION — analyze() handles everything
                            signal = analyze(df, coin['symbol'], tf)
                            if signal:
                                signal['alpha'] = coin['alpha']
                                signal['bybit_symbol'] = coin['bybit_symbol']
                                signal['volume_24h'] = coin['volume_24h']
                                signal['market_info'] = coin['market_info']
                                signal['is_volume_alpha'] = coin.get('is_volume_alpha', False)
                                signal['is_decoupled'] = coin.get('is_decoupled', False)
                                signal['is_new_listing'] = coin.get('is_new_listing', False)
                                signal['correlation'] = coin.get('correlation', 1.0)
                                signal['vol_ratio'] = coin.get('vol_ratio', 1.0)

                                signals.append(signal)
                                break  # 1 signal per koin cukup

                        if len(signals) >= slots:
                            break  # Enough signals

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
                                    alpha_pct=signal.get('alpha', 0),
                                    volume_ratio=signal['volume_ratio'],
                                    signal_data=json.dumps({
                                        'confidence': signal['confidence'],
                                        'stoch': signal['stoch_signal'],
                                        'hl_touches': signal['hl_touches'],
                                    }),
                                )

                                already_traded.add(signal['bybit_symbol'])
                                slots -= 1

                                # Telegram notification
                                await tg_signal(session, signal, sizing, result)

                                log.info(f"✅ TRADE EXECUTED: #{pos_id} {signal['bybit_symbol']} "
                                         f"@ {fill_price:.6f}")
                            else:
                                log.warning(f"Order failed for {signal['symbol']}")

                        except Exception as trade_err:
                            log.error(f"Trade execution error: {trade_err}")

                # ── Step 6: Log scan ────────────────────────────
                scan_ms = int((time.time() - t0) * 1000)
                WEB.scans += 1
                WEB.last_scan_time = datetime.utcnow().strftime('%H:%M:%S')
                WEB.last_scan_ms = scan_ms
                WEB.stats = db.get_stats()
                WEB.recent_trades = db.get_recent_trades(10)
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
        'alpha_coins': WEB.alpha_coins[:10],
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
