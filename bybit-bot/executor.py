"""
Bybit Crypto Algo Bot — Order Executor
Uses pybit (official Bybit SDK) for order execution.
SL/TP are set SERVER-SIDE on Bybit — they remain active even if bot dies.
"""
import logging
import time
from typing import Optional, Dict, List
from pybit.unified_trading import HTTP
from config import (
    BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET,
)

log = logging.getLogger('executor')


class BybitExecutor:
    """Handles all Bybit trading operations via pybit V5 API."""

    def __init__(self):
        self.session = HTTP(
            testnet=BYBIT_TESTNET,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET,
        )
        self._position_mode_set = set()  # Track which symbols had position mode set
        log.info(f"Bybit Executor initialized (testnet={BYBIT_TESTNET})")

    # ══════════════════════════════════════════════════════════
    # ACCOUNT INFO
    # ══════════════════════════════════════════════════════════

    def get_equity(self) -> float:
        """Get total equity in USDT (Unified + Funding)."""
        try:
            # 1. Total in Unified
            uta_equity = 0.0
            res_uta = self.session.get_wallet_balance(accountType="UNIFIED")
            if res_uta['retCode'] == 0:
                for coin in res_uta['result']['list']:
                    uta_equity += float(coin.get('totalEquity', 0))

            # 2. Total in Funding (Requires 'Asset' permission)
            fund_equity = 0.0
            try:
                res_fund = self.session.get_coins_balance(accountType="FUND", coin="USDT")
                if res_fund['retCode'] == 0:
                    for coin in res_fund['result']['list']:
                        fund_equity += float(coin.get('walletBalance', 0))
            except Exception as e:
                if '10005' in str(e):
                    log.warning("Funding account check skipped: API Key lacks 'Asset' permission.")
                else:
                    log.error(f"Funding balance check error: {e}")

            return uta_equity + fund_equity

        except Exception as e:
            log.error(f"Failed to get equity: {e}")
            return 0.0

    def get_balance(self) -> Dict:
        """Get detailed balance info across accounts."""
        try:
            data = {
                'uta_equity': 0.0,
                'uta_available': 0.0,
                'fund_equity': 0.0,
                'total_equity': 0.0
            }

            # UTA
            res_uta = self.session.get_wallet_balance(accountType="UNIFIED")
            if res_uta['retCode'] == 0:
                for coin in res_uta['result']['list']:
                    data['uta_equity'] += float(coin.get('totalEquity', 0))
                    data['uta_available'] += float(coin.get('totalAvailableBalance', 0))

            # Funding (Requires 'Asset' permission)
            try:
                res_fund = self.session.get_coins_balance(accountType="FUND", coin="USDT")
                if res_fund['retCode'] == 0:
                    for coin in res_fund['result']['list']:
                        data['fund_equity'] += float(coin.get('walletBalance', 0))
            except Exception as e:
                if '10005' in str(e):
                    pass # Silently skip dashboard detail for Fund
                else:
                    log.error(f"Funding check error: {e}")

            data['total_equity'] = data['uta_equity'] + data['fund_equity']
            return data

        except Exception as e:
            log.error(f"Balance check error: {e}")
            return {'uta_equity': 0, 'uta_available': 0, 'fund_equity': 0, 'total_equity': 0}



    def get_positions(self) -> List[Dict]:
        """Get all active USDT linear positions."""
        try:
            result = self.session.get_positions(category="linear", settleCoin="USDT")
            if result['retCode'] != 0:
                return []
            return result['result']['list']
        except Exception as e:
            log.error(f"Failed to get positions: {e}")
            return []


    # ══════════════════════════════════════════════════════════
    # LEVERAGE & MARGIN
    # ══════════════════════════════════════════════════════════

    def set_leverage(self, bybit_symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol. Must be called BEFORE placing order."""
        try:
            lev_str = str(leverage)
            result = self.session.set_leverage(
                category="linear",
                symbol=bybit_symbol,
                buyLeverage=lev_str,
                sellLeverage=lev_str,
            )

            ret_code = result.get('retCode', -1)

            # retCode 0 = success
            # retCode 110043 = leverage already set to this value (not an error)
            if ret_code == 0 or ret_code == 110043:
                log.info(f"Leverage set: {bybit_symbol} → {leverage}x")
                return True
            else:
                log.error(f"Set leverage failed: {result}")
                return False

        except Exception as e:
            err_str = str(e)
            if '110043' in err_str:
                # Already set to this value
                log.info(f"Leverage already {leverage}x for {bybit_symbol}")
                return True
            log.error(f"Set leverage error: {e}")
            return False

    def _ensure_position_mode(self, bybit_symbol: str):
        """Ensure one-way position mode (not hedge mode)."""
        if bybit_symbol in self._position_mode_set:
            return
        try:
            self.session.switch_position_mode(
                category="linear",
                symbol=bybit_symbol,
                mode=0,  # 0 = One-Way Mode
            )
        except Exception:
            pass  # Already in one-way mode or error — safe to ignore
        self._position_mode_set.add(bybit_symbol)

    # ══════════════════════════════════════════════════════════
    # ORDER EXECUTION
    # ══════════════════════════════════════════════════════════

    def open_long(self, bybit_symbol: str, qty: float, leverage: int,
                  sl_price: float, tp_price: float,
                  price_precision: float) -> Optional[Dict]:
        """
        Open a LONG position with server-side SL/TP.

        Steps:
        1. Set position mode (one-way)
        2. Set leverage
        3. Place market buy order with SL/TP

        The SL/TP live on BYBIT'S SERVER — if our bot dies, they stay active!
        """
        try:
            # Step 1: Position mode
            self._ensure_position_mode(bybit_symbol)

            # Step 2: Set leverage
            if not self.set_leverage(bybit_symbol, leverage):
                log.error(f"Cannot set leverage for {bybit_symbol}, aborting")
                return None

            # Step 3: Round SL/TP to price precision
            if price_precision > 0:
                sl_str = str(round(sl_price, self._count_decimals(price_precision)))
                tp_str = str(round(tp_price, self._count_decimals(price_precision)))
            else:
                sl_str = str(round(sl_price, 4))
                tp_str = str(round(tp_price, 4))

            qty_str = str(qty)

            # Step 4: Place market order with SL/TP
            log.info(f"📤 PLACING ORDER: {bybit_symbol} BUY qty={qty_str} "
                     f"lev={leverage}x SL={sl_str} TP={tp_str}")

            result = self.session.place_order(
                category="linear",
                symbol=bybit_symbol,
                side="Buy",
                orderType="Market",
                qty=qty_str,
                stopLoss=sl_str,
                takeProfit=tp_str,
                slTriggerBy="MarkPrice",
                tpTriggerBy="MarkPrice",
                timeInForce="GTC",
            )

            ret_code = result.get('retCode', -1)
            if ret_code != 0:
                log.error(f"❌ ORDER FAILED: {result.get('retMsg', 'Unknown error')}")
                return None

            order_id = result['result'].get('orderId', '')
            log.info(f"✅ ORDER PLACED: {bybit_symbol} orderId={order_id}")

            # Step 5: Verify — get the actual fill price
            time.sleep(0.5)
            fill_price = self._get_fill_price(bybit_symbol, order_id)

            return {
                'success': True,
                'order_id': order_id,
                'fill_price': fill_price,
                'qty': qty,
                'leverage': leverage,
                'sl_price': float(sl_str),
                'tp_price': float(tp_str),
            }

        except Exception as e:
            log.error(f"❌ OPEN LONG ERROR {bybit_symbol}: {e}")
            return None

    def close_long(self, bybit_symbol: str, qty: float) -> Optional[Dict]:
        """Close a LONG position by placing a market sell."""
        try:
            qty_str = str(qty)

            result = self.session.place_order(
                category="linear",
                symbol=bybit_symbol,
                side="Sell",
                orderType="Market",
                qty=qty_str,
                reduceOnly=True,
                timeInForce="GTC",
            )

            ret_code = result.get('retCode', -1)
            if ret_code != 0:
                log.error(f"❌ CLOSE FAILED: {result.get('retMsg', '')}")
                return None

            order_id = result['result'].get('orderId', '')
            log.info(f"✅ POSITION CLOSED: {bybit_symbol} orderId={order_id}")

            time.sleep(0.5)
            fill_price = self._get_fill_price(bybit_symbol, order_id)

            return {
                'success': True,
                'order_id': order_id,
                'fill_price': fill_price,
            }

        except Exception as e:
            log.error(f"❌ CLOSE ERROR {bybit_symbol}: {e}")
            return None

    # ══════════════════════════════════════════════════════════
    # POSITION MONITORING
    # ══════════════════════════════════════════════════════════

    def get_position(self, bybit_symbol: str) -> Optional[Dict]:
        """Get current position info from Bybit."""
        try:
            result = self.session.get_positions(
                category="linear",
                symbol=bybit_symbol,
            )

            if result['retCode'] != 0:
                return None

            positions = result['result']['list']
            for pos in positions:
                size = float(pos.get('size', 0))
                if size > 0:
                    return {
                        'symbol': bybit_symbol,
                        'side': pos.get('side', ''),
                        'size': size,
                        'entry_price': float(pos.get('avgPrice', 0)),
                        'mark_price': float(pos.get('markPrice', 0)),
                        'unrealized_pnl': float(pos.get('unrealisedPnl', 0)),
                        'leverage': int(float(pos.get('leverage', 1))),
                        'liq_price': float(pos.get('liqPrice', 0) or 0),
                        'stop_loss': float(pos.get('stopLoss', 0) or 0),
                        'take_profit': float(pos.get('takeProfit', 0) or 0),
                    }

            return None  # No position

        except Exception as e:
            log.error(f"Get position error {bybit_symbol}: {e}")
            return None

    def get_all_positions(self) -> List[Dict]:
        """Get all open positions."""
        try:
            result = self.session.get_positions(
                category="linear",
                settleCoin="USDT",
            )

            if result['retCode'] != 0:
                return []

            positions = []
            for pos in result['result']['list']:
                size = float(pos.get('size', 0))
                if size > 0:
                    positions.append({
                        'symbol': pos.get('symbol', ''),
                        'side': pos.get('side', ''),
                        'size': size,
                        'entry_price': float(pos.get('avgPrice', 0)),
                        'mark_price': float(pos.get('markPrice', 0)),
                        'unrealized_pnl': float(pos.get('unrealisedPnl', 0)),
                        'leverage': int(float(pos.get('leverage', 1))),
                        'liq_price': float(pos.get('liqPrice', 0) or 0),
                        'stop_loss': float(pos.get('stopLoss', 0) or 0),
                        'take_profit': float(pos.get('takeProfit', 0) or 0),
                    })

            return positions

        except Exception as e:
            log.error(f"Get all positions error: {e}")
            return []

    def update_sl_tp(self, bybit_symbol: str, sl_price: float = None,
                     tp_price: float = None) -> bool:
        """Update SL/TP on an existing position (server-side)."""
        try:
            params = {
                'category': 'linear',
                'symbol': bybit_symbol,
                'slTriggerBy': 'MarkPrice',
                'tpTriggerBy': 'MarkPrice',
            }
            if sl_price is not None:
                params['stopLoss'] = str(round(sl_price, 8))
            if tp_price is not None:
                params['takeProfit'] = str(round(tp_price, 8))

            result = self.session.set_trading_stop(**params)

            if result.get('retCode', -1) == 0:
                log.info(f"SL/TP updated for {bybit_symbol}: "
                         f"SL={sl_price} TP={tp_price}")
                return True
            else:
                log.error(f"Update SL/TP failed: {result.get('retMsg', '')}")
                return False

        except Exception as e:
            log.error(f"Update SL/TP error {bybit_symbol}: {e}")
            return False

    # ══════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════

    def _get_fill_price(self, bybit_symbol: str, order_id: str) -> float:
        """Get the actual fill price of an order."""
        try:
            result = self.session.get_order_history(
                category="linear",
                symbol=bybit_symbol,
                orderId=order_id,
            )
            if result['retCode'] == 0 and result['result']['list']:
                order = result['result']['list'][0]
                avg_price = float(order.get('avgPrice', 0))
                if avg_price > 0:
                    return avg_price
        except Exception:
            pass

        # Fallback: get from position
        try:
            pos = self.get_position(bybit_symbol)
            if pos:
                return pos['entry_price']
        except Exception:
            pass

        return 0.0

    @staticmethod
    def _count_decimals(precision: float) -> int:
        """Count decimal places from precision step (e.g., 0.01 → 2)."""
        if precision <= 0:
            return 4
        s = f"{precision:.10f}".rstrip('0')
        if '.' in s:
            return len(s.split('.')[1])
        return 0
