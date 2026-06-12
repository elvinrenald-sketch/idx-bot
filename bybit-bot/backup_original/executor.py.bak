"""
Hyperliquid Crypto Algo Bot — Order Executor
Uses hyperliquid-python-sdk for order execution on Hyperliquid DEX.
SL/TP are set as trigger orders on Hyperliquid's L1.
"""
import logging
import time
from typing import Optional, Dict, List

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL

from config import HL_PRIVATE_KEY, HL_WALLET_ADDRESS, HL_TESTNET

log = logging.getLogger('executor')


class HyperliquidExecutor:
    """Handles all Hyperliquid trading operations via official SDK."""

    def __init__(self):
        base_url = TESTNET_API_URL if HL_TESTNET else MAINNET_API_URL
        self.wallet = Account.from_key(HL_PRIVATE_KEY)
        self.address = HL_WALLET_ADDRESS or self.wallet.address
        self.info = Info(base_url, skip_ws=True)
        self.exchange = Exchange(self.wallet, base_url, account_address=self.address)
        self._meta = None  # Cache for asset metadata
        self._refresh_meta()
        log.info(f"Hyperliquid Executor initialized (testnet={HL_TESTNET}, address={self.address[:10]}...)")

    def _refresh_meta(self):
        """Refresh asset metadata from Hyperliquid."""
        try:
            self._meta = self.info.meta()
        except Exception as e:
            log.error(f"Failed to refresh meta: {e}")

    def _get_sz_decimals(self, coin: str) -> int:
        """Get size decimals for a coin from meta."""
        if self._meta:
            for asset_info in self._meta['universe']:
                if asset_info['name'] == coin:
                    return asset_info['szDecimals']
        return 2  # fallback

    _last_known_equity: float = 0.0

    def get_equity(self) -> float:
        """Get total account value in USD."""
        for attempt in range(3):
            try:
                state = self.info.user_state(self.address)
                equity = float(state['marginSummary']['accountValue'])
                if equity > 0:
                    HyperliquidExecutor._last_known_equity = equity
                return equity
            except Exception as e:
                err_str = str(e)
                if ('timed out' in err_str or 'timeout' in err_str.lower() or
                    'ConnectionError' in err_str) and attempt < 2:
                    wait = (attempt + 1) * 3
                    log.warning(f"⏳ get_equity timeout (attempt {attempt+1}/3). Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                log.error(f"Failed to get equity: {e}")
                break
        if HyperliquidExecutor._last_known_equity > 0:
            log.warning(f"Using cached equity: ${HyperliquidExecutor._last_known_equity:.2f}")
            return HyperliquidExecutor._last_known_equity
        return 0.0

    def get_balance(self) -> Dict:
        """Get detailed balance info."""
        default = {'uta_equity': 0, 'uta_available': 0, 'fund_equity': 0, 'total_equity': 0}
        for attempt in range(3):
            try:
                state = self.info.user_state(self.address)
                margin = state['marginSummary']
                equity = float(margin['accountValue'])
                available = float(state.get('withdrawable', 0))
                return {
                    'uta_equity': equity,
                    'uta_available': available,
                    'fund_equity': 0.0,
                    'total_equity': equity
                }
            except Exception as e:
                err_str = str(e)
                if ('timed out' in err_str or 'timeout' in err_str.lower()) and attempt < 2:
                    wait = (attempt + 1) * 3
                    log.warning(f"⏳ get_balance timeout (attempt {attempt+1}/3). Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                log.error(f"Balance check error: {e}")
                break
        return default

    def get_positions(self) -> List[Dict]:
        """Get all active positions (raw list for sync)."""
        for attempt in range(3):
            try:
                state = self.info.user_state(self.address)
                positions = []
                for ap in state.get('assetPositions', []):
                    pos = ap['position']
                    szi = float(pos['szi'])
                    if szi != 0:
                        positions.append(pos)  # Return raw position dicts
                return positions
            except Exception as e:
                err_str = str(e)
                if ('timed out' in err_str or 'timeout' in err_str.lower()) and attempt < 2:
                    wait = (attempt + 1) * 3
                    log.warning(f"⏳ get_positions timeout (attempt {attempt+1}/3). Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                log.error(f"Failed to get positions: {e}")
                return []
        return []

    def set_leverage(self, bybit_symbol: str, leverage: int) -> bool:
        """Set leverage for a coin. Must be called BEFORE placing order."""
        try:
            # Hyperliquid: update_leverage(leverage, coin, is_cross)
            # We use isolated margin (is_cross=False)
            self.exchange.update_leverage(leverage, bybit_symbol, is_cross=False)
            log.info(f"Leverage set: {bybit_symbol} → {leverage}x (isolated)")
            return True
        except Exception as e:
            err_str = str(e)
            # If leverage is already set, treat as success
            if 'already' in err_str.lower() or 'same' in err_str.lower():
                log.info(f"Leverage already {leverage}x for {bybit_symbol}")
                return True
            log.error(f"Set leverage error: {e}")
            return False

    def open_long(self, bybit_symbol: str, qty: float, leverage: int,
                  sl_price: float, tp_price: float,
                  price_precision: float) -> Optional[Dict]:
        """Open a LONG position with SL/TP trigger orders."""
        try:
            # Step 1: Set leverage
            if not self.set_leverage(bybit_symbol, leverage):
                log.error(f"Cannot set leverage for {bybit_symbol}, aborting")
                return None

            # Step 2: Round qty to sz_decimals
            sz_decimals = self._get_sz_decimals(bybit_symbol)
            qty = round(qty, sz_decimals)

            # Step 3: Place market buy with SL/TP as TPSL group
            log.info(f"📤 PLACING ORDER: {bybit_symbol} BUY qty={qty} "
                     f"lev={leverage}x SL={sl_price} TP={tp_price}")

            result = None
            for attempt in range(3):
                try:
                    result = self.exchange.market_open(
                        bybit_symbol, True, qty, slippage=0.01
                    )
                    break
                except Exception as order_err:
                    err_str = str(order_err)
                    if ('timed out' in err_str or 'timeout' in err_str.lower()) and attempt < 2:
                        wait = (attempt + 1) * 3
                        log.warning(f"⏳ Order timeout (attempt {attempt+1}/3). Checking in {wait}s...")
                        time.sleep(wait)
                        pos = self.get_position(bybit_symbol)
                        if pos and pos['size'] > 0:
                            log.info(f"✅ Order went through despite timeout! size={pos['size']}")
                            # Place SL/TP trigger orders
                            self._place_sl_tp(bybit_symbol, qty, False, sl_price, tp_price, price_precision)
                            return {
                                'success': True,
                                'order_id': 'timeout-recovery',
                                'fill_price': pos['entry_price'],
                                'qty': pos['size'],
                                'leverage': leverage,
                                'sl_price': sl_price,
                                'tp_price': tp_price,
                            }
                        continue
                    raise

            if result is None:
                log.error(f"❌ ORDER FAILED after 3 retries: {bybit_symbol}")
                return None

            # Check result
            statuses = result.get('response', {}).get('data', {}).get('statuses', [])
            if not statuses or 'error' in str(statuses[0]).lower():
                log.error(f"❌ ORDER FAILED: {statuses}")
                return None

            # Get fill info
            filled = statuses[0].get('filled', statuses[0].get('resting', {}))
            fill_price = float(filled.get('avgPx', 0)) if filled else 0
            total_sz = float(filled.get('totalSz', qty)) if filled else qty

            log.info(f"✅ ORDER PLACED: {bybit_symbol} fill_price={fill_price}")

            # Step 4: Place SL/TP trigger orders
            time.sleep(0.5)
            self._place_sl_tp(bybit_symbol, total_sz, False, sl_price, tp_price, price_precision)

            # If fill_price is 0, get from position
            if fill_price <= 0:
                time.sleep(0.5)
                pos = self.get_position(bybit_symbol)
                if pos:
                    fill_price = pos['entry_price']

            return {
                'success': True,
                'order_id': str(filled.get('oid', '')) if filled else '',
                'fill_price': fill_price,
                'qty': total_sz,
                'leverage': leverage,
                'sl_price': sl_price,
                'tp_price': tp_price,
            }

        except Exception as e:
            log.error(f"❌ OPEN LONG ERROR {bybit_symbol}: {e}")
            return None

    def open_short(self, bybit_symbol: str, qty: float, leverage: int,
                   sl_price: float, tp_price: float,
                   price_precision: float) -> Optional[Dict]:
        """Open a SHORT position with SL/TP trigger orders."""
        try:
            if not self.set_leverage(bybit_symbol, leverage):
                log.error(f"Cannot set leverage for {bybit_symbol}, aborting SHORT")
                return None

            sz_decimals = self._get_sz_decimals(bybit_symbol)
            qty = round(qty, sz_decimals)

            log.info(f"📤 PLACING SHORT ORDER: {bybit_symbol} SELL qty={qty} "
                     f"lev={leverage}x SL={sl_price} TP={tp_price}")

            result = None
            for attempt in range(3):
                try:
                    result = self.exchange.market_open(
                        bybit_symbol, False, qty, slippage=0.01
                    )
                    break
                except Exception as order_err:
                    err_str = str(order_err)
                    if ('timed out' in err_str or 'timeout' in err_str.lower()) and attempt < 2:
                        wait = (attempt + 1) * 3
                        log.warning(f"⏳ Short order timeout (attempt {attempt+1}/3). Checking in {wait}s...")
                        time.sleep(wait)
                        pos = self.get_position(bybit_symbol)
                        if pos and pos['size'] > 0:
                            log.info(f"✅ Short order went through despite timeout! size={pos['size']}")
                            self._place_sl_tp(bybit_symbol, qty, True, sl_price, tp_price, price_precision)
                            return {
                                'success': True,
                                'order_id': 'timeout-recovery',
                                'fill_price': pos['entry_price'],
                                'qty': pos['size'],
                                'leverage': leverage,
                                'sl_price': sl_price,
                                'tp_price': tp_price,
                            }
                        continue
                    raise

            if result is None:
                log.error(f"❌ SHORT ORDER FAILED after 3 retries: {bybit_symbol}")
                return None

            statuses = result.get('response', {}).get('data', {}).get('statuses', [])
            if not statuses or 'error' in str(statuses[0]).lower():
                log.error(f"❌ SHORT ORDER FAILED: {statuses}")
                return None

            filled = statuses[0].get('filled', statuses[0].get('resting', {}))
            fill_price = float(filled.get('avgPx', 0)) if filled else 0
            total_sz = float(filled.get('totalSz', qty)) if filled else qty

            log.info(f"✅ SHORT ORDER PLACED: {bybit_symbol} fill_price={fill_price}")

            time.sleep(0.5)
            self._place_sl_tp(bybit_symbol, total_sz, True, sl_price, tp_price, price_precision)

            if fill_price <= 0:
                time.sleep(0.5)
                pos = self.get_position(bybit_symbol)
                if pos:
                    fill_price = pos['entry_price']

            return {
                'success': True,
                'order_id': str(filled.get('oid', '')) if filled else '',
                'fill_price': fill_price,
                'qty': total_sz,
                'leverage': leverage,
                'sl_price': sl_price,
                'tp_price': tp_price,
            }

        except Exception as e:
            log.error(f"❌ OPEN SHORT ERROR {bybit_symbol}: {e}")
            return None

    def _place_sl_tp(self, coin: str, qty: float, is_short: bool,
                     sl_price: float, tp_price: float,
                     price_precision: float):
        """Place SL and TP trigger orders for an existing position."""
        try:
            decimals = self._count_decimals(price_precision) if price_precision > 0 else 6
            sl_px = round(sl_price, decimals)
            tp_px = round(tp_price, decimals)

            # SL order: opposite side, reduce_only, trigger
            # For LONG: sell at sl_price (market)
            # For SHORT: buy at sl_price (market)
            is_buy_for_exit = is_short  # SHORT exit = BUY, LONG exit = SELL

            orders = [
                {
                    "coin": coin,
                    "is_buy": is_buy_for_exit,
                    "sz": qty,
                    "limit_px": sl_px,
                    "order_type": {"trigger": {"triggerPx": float(sl_px), "isMarket": True, "tpsl": "sl"}},
                    "reduce_only": True,
                },
                {
                    "coin": coin,
                    "is_buy": is_buy_for_exit,
                    "sz": qty,
                    "limit_px": tp_px,
                    "order_type": {"trigger": {"triggerPx": float(tp_px), "isMarket": True, "tpsl": "tp"}},
                    "reduce_only": True,
                },
            ]

            result = self.exchange.bulk_orders(orders, grouping="positionTpsl")
            log.info(f"SL/TP set for {coin}: SL={sl_px} TP={tp_px}")
            return result
        except Exception as e:
            log.error(f"Failed to set SL/TP for {coin}: {e}")

    def close_long(self, bybit_symbol: str, qty: float) -> Optional[Dict]:
        """Close a LONG position (partial or full)."""
        try:
            sz_decimals = self._get_sz_decimals(bybit_symbol)
            qty = round(qty, sz_decimals)

            result = None
            for attempt in range(3):
                try:
                    # market_close will close the full position
                    # For partial close, use market_open with reduce_only via order()
                    if qty > 0:
                        # Partial close: SELL to reduce LONG
                        result = self.exchange.order(
                            bybit_symbol, False, qty,
                            self.exchange._slippage_price(bybit_symbol, False, 0.01),
                            order_type={"limit": {"tif": "Ioc"}},
                            reduce_only=True
                        )
                    else:
                        result = self.exchange.market_close(bybit_symbol)
                    break
                except Exception as close_err:
                    err_str = str(close_err)
                    if ('timed out' in err_str or 'timeout' in err_str.lower()) and attempt < 2:
                        wait = (attempt + 1) * 3
                        log.warning(f"⏳ Close order timeout (attempt {attempt+1}/3). Checking in {wait}s...")
                        time.sleep(wait)
                        pos = self.get_position(bybit_symbol)
                        if pos is None or pos['size'] == 0:
                            log.info(f"✅ Position closed despite timeout!")
                            return {'success': True, 'order_id': 'timeout-recovery', 'fill_price': 0.0}
                        continue
                    raise

            if result is None:
                log.error(f"❌ CLOSE FAILED after 3 retries: {bybit_symbol}")
                return None

            statuses = result.get('response', {}).get('data', {}).get('statuses', [])
            if statuses and 'error' in str(statuses[0]).lower():
                log.error(f"❌ CLOSE FAILED: {statuses}")
                return None

            filled = statuses[0].get('filled', {}) if statuses else {}
            fill_price = float(filled.get('avgPx', 0)) if filled else 0

            log.info(f"✅ POSITION CLOSED: {bybit_symbol}")
            return {
                'success': True,
                'order_id': str(filled.get('oid', '')) if filled else '',
                'fill_price': fill_price,
            }

        except Exception as e:
            log.error(f"❌ CLOSE ERROR {bybit_symbol}: {e}")
            return None

    def close_short(self, bybit_symbol: str, qty: float) -> Optional[Dict]:
        """Close a SHORT position (partial or full)."""
        try:
            sz_decimals = self._get_sz_decimals(bybit_symbol)
            qty = round(qty, sz_decimals)

            result = None
            for attempt in range(3):
                try:
                    if qty > 0:
                        # Partial close: BUY to reduce SHORT
                        result = self.exchange.order(
                            bybit_symbol, True, qty,
                            self.exchange._slippage_price(bybit_symbol, True, 0.01),
                            order_type={"limit": {"tif": "Ioc"}},
                            reduce_only=True
                        )
                    else:
                        result = self.exchange.market_close(bybit_symbol)
                    break
                except Exception as close_err:
                    err_str = str(close_err)
                    if ('timed out' in err_str or 'timeout' in err_str.lower()) and attempt < 2:
                        wait = (attempt + 1) * 3
                        log.warning(f"⏳ Close short timeout (attempt {attempt+1}/3). Checking in {wait}s...")
                        time.sleep(wait)
                        pos = self.get_position(bybit_symbol)
                        if pos is None or pos['size'] == 0:
                            log.info(f"✅ Short position closed despite timeout!")
                            return {'success': True, 'order_id': 'timeout-recovery', 'fill_price': 0.0}
                        continue
                    raise

            if result is None:
                log.error(f"❌ CLOSE SHORT FAILED after 3 retries: {bybit_symbol}")
                return None

            statuses = result.get('response', {}).get('data', {}).get('statuses', [])
            if statuses and 'error' in str(statuses[0]).lower():
                log.error(f"❌ CLOSE SHORT FAILED: {statuses}")
                return None

            filled = statuses[0].get('filled', {}) if statuses else {}
            fill_price = float(filled.get('avgPx', 0)) if filled else 0

            log.info(f"✅ SHORT POSITION CLOSED: {bybit_symbol}")
            return {
                'success': True,
                'order_id': str(filled.get('oid', '')) if filled else '',
                'fill_price': fill_price,
            }

        except Exception as e:
            log.error(f"❌ CLOSE SHORT ERROR {bybit_symbol}: {e}")
            return None

    def get_position(self, bybit_symbol: str) -> Optional[Dict]:
        """Get current position info for a specific coin."""
        for attempt in range(3):
            try:
                state = self.info.user_state(self.address)
                for ap in state.get('assetPositions', []):
                    pos = ap['position']
                    if pos['coin'] == bybit_symbol:
                        szi = float(pos['szi'])
                        if abs(szi) > 0:
                            entry_px = float(pos.get('entryPx', 0) or 0)
                            liq_px = float(pos.get('liquidationPx', 0) or 0)
                            unrealized = float(pos.get('unrealizedPnl', 0) or 0)
                            lev_info = pos.get('leverage', {})
                            lev = int(lev_info.get('value', 1))

                            return {
                                'symbol': bybit_symbol,
                                'side': 'Sell' if szi < 0 else 'Buy',
                                'size': abs(szi),
                                'entry_price': entry_px,
                                'mark_price': entry_px,  # HL doesn't return mark directly in user_state
                                'unrealized_pnl': unrealized,
                                'leverage': lev,
                                'liq_price': liq_px,
                                'stop_loss': 0.0,   # HL manages triggers separately
                                'take_profit': 0.0,  # HL manages triggers separately
                            }
                return None
            except Exception as e:
                err_str = str(e)
                if ('timed out' in err_str or 'timeout' in err_str.lower()) and attempt < 2:
                    wait = (attempt + 1) * 2
                    log.warning(f"⏳ get_position timeout {bybit_symbol} (attempt {attempt+1}/3). Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                log.error(f"Get position error {bybit_symbol}: {e}")
                return None
        return None

    def get_all_positions(self) -> List[Dict]:
        """Get all open positions."""
        for attempt in range(3):
            try:
                state = self.info.user_state(self.address)
                positions = []
                for ap in state.get('assetPositions', []):
                    pos = ap['position']
                    szi = float(pos['szi'])
                    if abs(szi) > 0:
                        entry_px = float(pos.get('entryPx', 0) or 0)
                        liq_px = float(pos.get('liquidationPx', 0) or 0)
                        unrealized = float(pos.get('unrealizedPnl', 0) or 0)
                        lev_info = pos.get('leverage', {})
                        lev = int(lev_info.get('value', 1))

                        positions.append({
                            'symbol': pos['coin'],
                            'side': 'Sell' if szi < 0 else 'Buy',
                            'size': abs(szi),
                            'entry_price': entry_px,
                            'mark_price': entry_px,
                            'unrealized_pnl': unrealized,
                            'leverage': lev,
                            'liq_price': liq_px,
                            'stop_loss': 0.0,
                            'take_profit': 0.0,
                        })
                return positions
            except Exception as e:
                err_str = str(e).lower()
                if ('timed out' in err_str or 'timeout' in err_str) and attempt < 2:
                    wait = 5 * (attempt + 1)
                    log.warning(f"⏱️ Get positions timeout, retry in {wait}s (Attempt {attempt+1}/3)")
                    time.sleep(wait)
                else:
                    log.error(f"Get all positions error: {e}")
                    return []
        return []

    def update_sl_tp(self, bybit_symbol: str, sl_price: float = None,
                     tp_price: float = None) -> bool:
        """Update SL/TP on an existing position.

        Strategy: Cancel existing trigger orders, place new ones.
        This is needed because Hyperliquid trigger orders are separate orders,
        not position attributes like on Bybit.
        """
        for attempt in range(3):
            try:
                # First, cancel existing open trigger orders for this coin
                open_orders = self.info.open_orders(self.address)
                for order in open_orders:
                    if order.get('coin') == bybit_symbol:
                        try:
                            self.exchange.cancel(bybit_symbol, order['oid'])
                        except Exception:
                            pass  # Best effort cancel

                # Get current position to know size and side
                pos = self.get_position(bybit_symbol)
                if not pos:
                    log.warning(f"No position found for {bybit_symbol}, skip SL/TP update")
                    return False

                is_short = (pos['side'] == 'Sell')
                qty = pos['size']
                is_buy_for_exit = is_short  # Exit side

                orders = []
                if sl_price is not None:
                    sl_px = round(sl_price, 8)
                    orders.append({
                        "coin": bybit_symbol,
                        "is_buy": is_buy_for_exit,
                        "sz": qty,
                        "limit_px": sl_px,
                        "order_type": {"trigger": {"triggerPx": float(sl_px), "isMarket": True, "tpsl": "sl"}},
                        "reduce_only": True,
                    })
                if tp_price is not None:
                    tp_px = round(tp_price, 8)
                    orders.append({
                        "coin": bybit_symbol,
                        "is_buy": is_buy_for_exit,
                        "sz": qty,
                        "limit_px": tp_px,
                        "order_type": {"trigger": {"triggerPx": float(tp_px), "isMarket": True, "tpsl": "tp"}},
                        "reduce_only": True,
                    })

                if orders:
                    self.exchange.bulk_orders(orders, grouping="positionTpsl")
                    log.info(f"SL/TP updated for {bybit_symbol}: SL={sl_price} TP={tp_price}")
                return True

            except Exception as e:
                err_str = str(e)
                if ('timed out' in err_str or 'timeout' in err_str.lower()) and attempt < 2:
                    wait = (attempt + 1) * 3
                    log.warning(f"⏳ update_sl_tp timeout (attempt {attempt+1}/3). Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                log.error(f"Update SL/TP error {bybit_symbol}: {e}")
                return False
        return False

    @staticmethod
    def _count_decimals(precision: float) -> int:
        """Count decimal places from precision step (e.g., 0.01 → 2)."""
        if precision <= 0:
            return 4
        s = f"{precision:.10f}".rstrip('0')
        if '.' in s:
            return len(s.split('.')[1])
        return 0
