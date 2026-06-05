"""
Hyperliquid Crypto Algo Bot — Market Scanner
Scans Hyperliquid perp markets for alpha and volume.
Migrated from Bybit (ccxt) to Hyperliquid Info API.
"""
import logging
import time
import requests
import math
from typing import List, Dict, Optional
import pandas as pd

from hyperliquid.info import Info
from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL

from config import (
    HL_TESTNET,
    MIN_VOLUME_24H, MAX_VOLUME_24H, MIN_PRICE,
    BLACKLIST_SYMBOLS, MAX_SPREAD_PCT,
    MAX_ALPHA_COINS, ALPHA_THRESHOLD_PCT,
    ALPHA_LOOKBACK_H, CANDLE_LOOKBACK,
    TIMEFRAMES, RATE_LIMIT_DELAY,
    VOLUME_ALPHA_THRESHOLD, BTC_VOLUME_MAX_RATIO,
    DECOUPLING_THRESHOLD, DECOUPLING_WINDOW_H,
    NEW_LISTING_DAYS,
    MARKETCAP_TOP_N, MARKETCAP_CACHE_SEC,
)

log = logging.getLogger('scanner')

# Timeframe to interval string mapping for Hyperliquid candles API
TF_MAP = {
    '1m': '1m',
    '5m': '5m',
    '15m': '15m',
    '30m': '30m',
    '1h': '1h',
    '4h': '4h',
    '1d': '1d',
    '1w': '1w',
    '1M': '1M',
}


class MarketScanner:
    """Scans Hyperliquid perpetual markets for trading opportunities."""

    def __init__(self):
        base_url = TESTNET_API_URL if HL_TESTNET else MAINNET_API_URL
        self.info = Info(base_url, skip_ws=True)
        self.markets_info: Dict = {}  # coin -> market info dict
        self._markets_loaded = False
        self._meta = None
        self._asset_ctxs = None
        # CoinGecko cache
        self._mcap_symbols: set = set()
        self._mcap_last_fetch: float = 0.0
        log.info(f"Scanner initialized (Hyperliquid, testnet={HL_TESTNET})")

    def load_markets(self):
        """Load all available perp markets from Hyperliquid."""
        try:
            meta = self.info.meta()
            self._meta = meta
            
            # Get asset contexts for additional data
            # meta_and_ctxs returns [meta, [ctx_per_asset]]
            # Each ctx has: dayNtlVlm, funding, impactPxs, markPx, midPx, openInterest, oraclePx, premium, prevDayPx
            meta_and_ctxs = self.info.meta_and_asset_ctxs()
            self._asset_ctxs = meta_and_ctxs[1] if len(meta_and_ctxs) > 1 else []
            
            self.markets_info = {}
            universe = meta.get('universe', [])
            
            for i, asset_info in enumerate(universe):
                coin = asset_info['name']  # e.g., 'BTC', 'ETH', 'SOL'
                sz_decimals = asset_info.get('szDecimals', 2)
                
                # Calculate qty_step and price precision from szDecimals
                qty_step = 10 ** (-sz_decimals)
                min_qty = qty_step
                
                # Price precision: Hyperliquid uses 5 significant figures
                # Use asset context for current price to determine price_precision
                price_precision = 0.0001  # Default
                if i < len(self._asset_ctxs):
                    ctx = self._asset_ctxs[i]
                    mark_px = float(ctx.get('markPx', 0) or 0)
                    if mark_px > 0:
                        # 5 sig figs for HL
                        mag = math.floor(math.log10(mark_px)) if mark_px > 0 else 0
                        price_precision = 10 ** (mag - 4)  # 5 sig figs
                
                self.markets_info[coin] = {
                    'id': coin,          # Same as coin name
                    'base': coin,
                    'quote': 'USDC',
                    'min_qty': min_qty,
                    'qty_step': qty_step,
                    'price_precision': price_precision,
                    'sz_decimals': sz_decimals,
                    'asset_index': i,
                }
            
            self._markets_loaded = True
            log.info(f"Loaded {len(self.markets_info)} Hyperliquid perp markets")
            
        except Exception as e:
            log.error(f"Failed to load markets: {e}")
            raise

    def get_market_info(self, coin: str) -> Optional[Dict]:
        """Get market info for a specific coin."""
        return self.markets_info.get(coin)

    def _get_pct_change(self, df: pd.DataFrame, hours: int) -> float:
        """Calculate percentage change over N hours from OHLCV data."""
        if df is None or len(df) < hours:
            return 0.0
        old_price = float(df['close'].iloc[-hours])
        new_price = float(df['close'].iloc[-1])
        if old_price <= 0:
            return 0.0
        return ((new_price - old_price) / old_price) * 100

    def fetch_btc_trend_bias(self) -> str:
        """Determine BTC trend bias using EMA on H4 candles."""
        try:
            df = self.fetch_ohlcv('BTC', '4h', limit=50)
            if df is None or len(df) < 14:
                return 'NEUTRAL'

            # Calculate 13 EMA
            ema13 = df['close'].ewm(span=13, adjust=False).mean()
            last_close = df['close'].iloc[-1]
            last_ema = ema13.iloc[-1]

            if last_close > last_ema:
                return 'LONG'
            elif last_close < last_ema:
                return 'SHORT'
            return 'NEUTRAL'
        except Exception as e:
            log.warning(f"BTC trend bias error: {e}")
            return 'NEUTRAL'

    def scan_for_alpha(self) -> List[Dict]:
        """Scan for alpha coins outperforming BTC in last 4h."""
        if not self._markets_loaded:
            self.load_markets()

        # Get all mid prices
        try:
            all_mids = self.info.all_mids()
        except Exception as e:
            log.error(f"Failed to fetch all_mids: {e}")
            return []

        # Refresh asset contexts for volume data
        try:
            meta_and_ctxs = self.info.meta_and_asset_ctxs()
            self._asset_ctxs = meta_and_ctxs[1] if len(meta_and_ctxs) > 1 else []
        except Exception:
            pass

        # Get BTC 4h data
        btc_df = self.fetch_ohlcv('BTC', '1h', limit=24)
        btc_change_4h = self._get_pct_change(btc_df, ALPHA_LOOKBACK_H) if btc_df is not None else 0
        btc_vol_ratio = 1.0
        if btc_df is not None and len(btc_df) > 4:
            btc_vol_recent = btc_df['volume'].iloc[-4:].mean()
            btc_vol_avg = btc_df['volume'].mean()
            btc_vol_ratio = btc_vol_recent / btc_vol_avg if btc_vol_avg > 0 else 1.0

        alpha_coins = []
        universe = self._meta.get('universe', []) if self._meta else []

        for i, asset_info in enumerate(universe):
            coin = asset_info['name']
            if coin in BLACKLIST_SYMBOLS or coin == 'BTC':
                continue
            if coin not in self.markets_info:
                continue

            try:
                # Get volume from asset context
                vol_24h = 0.0
                price_now = 0.0
                prev_day_px = 0.0
                if i < len(self._asset_ctxs):
                    ctx = self._asset_ctxs[i]
                    vol_24h = float(ctx.get('dayNtlVlm', 0) or 0)
                    price_now = float(ctx.get('markPx', 0) or 0)
                    prev_day_px = float(ctx.get('prevDayPx', 0) or 0)

                if price_now <= 0:
                    price_now = float(all_mids.get(coin, 0) or 0)

                if vol_24h < MIN_VOLUME_24H or vol_24h > MAX_VOLUME_24H or price_now < MIN_PRICE:
                    continue

                # 24h change
                pct_change_24h = ((price_now - prev_day_px) / prev_day_px * 100) if prev_day_px > 0 else 0

                # 4h change
                coin_df = self.fetch_ohlcv(coin, '1h', limit=24)
                if coin_df is None or len(coin_df) < ALPHA_LOOKBACK_H:
                    continue

                pct_change_4h = self._get_pct_change(coin_df, ALPHA_LOOKBACK_H)
                alpha_4h = pct_change_4h - btc_change_4h

                if alpha_4h < ALPHA_THRESHOLD_PCT:
                    continue

                # Volume Alpha
                coin_vol_recent = coin_df['volume'].iloc[-4:].mean()
                coin_vol_avg = coin_df['volume'].mean()
                coin_vol_ratio = coin_vol_recent / coin_vol_avg if coin_vol_avg > 0 else 1.0
                is_volume_alpha = (coin_vol_ratio >= VOLUME_ALPHA_THRESHOLD) and (btc_vol_ratio <= BTC_VOLUME_MAX_RATIO)

                # Decoupling
                correlation = self._calculate_correlation(coin_df, btc_df)
                is_decoupled = correlation <= DECOUPLING_THRESHOLD

                # New listing
                history_len = len(coin_df)
                is_new_listing = history_len <= (NEW_LISTING_DAYS * 24)

                info = self.markets_info[coin]

                alpha_coins.append({
                    'symbol': coin,
                    'bybit_symbol': coin,  # Keep field name for compatibility
                    'base': coin,
                    'price': float(price_now),
                    'volume_24h': float(vol_24h),
                    'pct_change_24h': float(pct_change_24h),
                    'pct_change_4h': float(round(pct_change_4h, 2)),
                    'btc_change_4h': float(round(btc_change_4h, 2)),
                    'alpha': float(round(alpha_4h, 2)),
                    'spread_pct': 0.0,  # HL has tight spreads
                    'market_info': info,
                    'is_volume_alpha': bool(is_volume_alpha),
                    'is_decoupled': bool(is_decoupled),
                    'is_new_listing': bool(is_new_listing),
                    'correlation': float(round(correlation, 3)),
                    'vol_ratio': float(round(coin_vol_ratio, 2))
                })

            except Exception:
                continue

        alpha_coins.sort(key=lambda x: x['alpha'], reverse=True)
        result = alpha_coins[:MAX_ALPHA_COINS]

        log.info(f"Alpha scan finished: {len(alpha_coins)} alpha found → top {len(result)} selected")
        if result:
            top3 = ', '.join([f"{c['base']}({c['alpha']:+.1f}%)" for c in result[:3]])
            log.info(f"Top 4h Alpha: {top3}")

        return result

    def _fetch_top_marketcap_symbols(self) -> set:
        """Fetch top N coins by market cap from CoinGecko."""
        now = time.time()
        if self._mcap_symbols and (now - self._mcap_last_fetch) < MARKETCAP_CACHE_SEC:
            return self._mcap_symbols

        if not self._mcap_symbols and getattr(self, '_cg_cooldown_until', 0) > now:
            return self._mcap_symbols

        try:
            symbols = set()
            per_page = min(MARKETCAP_TOP_N, 250)
            url = 'https://api.coingecko.com/api/v3/coins/markets'
            params = {
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': per_page,
                'page': 1,
                'sparkline': 'false',
            }
            resp = requests.get(url, params=params, timeout=15)

            if resp.status_code == 429:
                log.warning("CoinGecko API rate limit (429). Cooling down for 5 minutes.")
                self._cg_cooldown_until = now + 300
                return self._mcap_symbols

            resp.raise_for_status()
            data = resp.json()

            for coin in data:
                sym = coin.get('symbol', '').upper()
                if sym:
                    symbols.add(sym)

            self._mcap_symbols = symbols
            self._mcap_last_fetch = now
            log.info(f"📊 CoinGecko top {MARKETCAP_TOP_N} market cap loaded: {len(symbols)} symbols")
            return symbols

        except Exception as e:
            log.warning(f"CoinGecko API error: {e} — using cached or skipping filter")
            self._cg_cooldown_until = now + 120
            return self._mcap_symbols

    def scan_top_volume(self) -> List[Dict]:
        """Scan top 60 coins by 24h volume."""
        if not self._markets_loaded:
            self.load_markets()

        # Refresh asset contexts for volume data
        try:
            meta_and_ctxs = self.info.meta_and_asset_ctxs()
            self._asset_ctxs = meta_and_ctxs[1] if len(meta_and_ctxs) > 1 else []
        except Exception as e:
            log.error(f"Failed to refresh meta: {e}")
            return []

        all_mids = {}
        try:
            all_mids = self.info.all_mids()
        except Exception:
            pass

        candidates = []
        mcap_symbols = self._fetch_top_marketcap_symbols()
        mcap_filtered = 0
        universe = self._meta.get('universe', []) if self._meta else []

        for i, asset_info in enumerate(universe):
            coin = asset_info['name']
            if coin in BLACKLIST_SYMBOLS:
                continue

            try:
                vol_24h = 0.0
                last_price = 0.0
                if i < len(self._asset_ctxs):
                    ctx = self._asset_ctxs[i]
                    vol_24h = float(ctx.get('dayNtlVlm', 0) or 0)
                    last_price = float(ctx.get('markPx', 0) or 0)

                if last_price <= 0:
                    last_price = float(all_mids.get(coin, 0) or 0)

                if vol_24h < MIN_VOLUME_24H or vol_24h > MAX_VOLUME_24H or last_price < MIN_PRICE:
                    continue

                # Market cap filter
                if mcap_symbols:
                    base_upper = coin.upper()
                    normalized = base_upper
                    if normalized.startswith('1000'):
                        normalized = normalized[4:]
                    elif normalized.endswith('1000'):
                        normalized = normalized[:-4]
                    if base_upper in mcap_symbols or normalized in mcap_symbols:
                        mcap_filtered += 1
                        continue

                prev_day_px = 0.0
                if i < len(self._asset_ctxs):
                    prev_day_px = float(self._asset_ctxs[i].get('prevDayPx', 0) or 0)
                pct_change_24h = ((last_price - prev_day_px) / prev_day_px * 100) if prev_day_px > 0 else 0

                info = self.markets_info.get(coin, {})
                candidates.append({
                    'symbol': coin,
                    'bybit_symbol': coin,  # Keep field name for compatibility
                    'base': coin,
                    'price': last_price,
                    'volume_24h': vol_24h,
                    'pct_change_24h': float(pct_change_24h),
                    'spread_pct': 0.0,
                    'market_info': info,
                    'alpha': 0.0,
                    'is_volume_alpha': False,
                    'is_decoupled': False,
                    'is_new_listing': False,
                    'correlation': 1.0,
                    'vol_ratio': 1.0,
                })
            except (TypeError, ValueError):
                continue

        candidates.sort(key=lambda x: x['volume_24h'], reverse=True)
        result = candidates[:60]

        log.info(f"Volume scan: {len(candidates)} candidates → top {len(result)} by volume "
                 f"(skipped {mcap_filtered} coins because they are IN top-{MARKETCAP_TOP_N} mcap)")
        if result:
            top3 = ', '.join([f"{c['base']}(${c['volume_24h']/1e6:.0f}M)" for c in result[:3]])
            log.info(f"Top volume: {top3}")

        return result

    def fetch_ohlcv(self, symbol: str, timeframe: str,
                    limit: int = CANDLE_LOOKBACK) -> Optional[pd.DataFrame]:
        """Fetch OHLCV candlestick data from Hyperliquid."""
        max_retries = 3
        hl_interval = TF_MAP.get(timeframe, timeframe)

        for attempt in range(max_retries):
            try:
                time.sleep(RATE_LIMIT_DELAY)

                # Calculate start time (limit candles back)
                # Each interval in seconds
                interval_secs = {
                    '1m': 60, '5m': 300, '15m': 900, '30m': 1800,
                    '1h': 3600, '4h': 14400, '1d': 86400, '1w': 604800,
                }
                secs = interval_secs.get(timeframe, 3600)
                end_time = int(time.time() * 1000)
                start_time = end_time - (limit * secs * 1000)

                data = self.info.candles_snapshot(
                    coin=symbol,
                    interval=hl_interval,
                    startTime=start_time,
                    endTime=end_time
                )

                if not data or len(data) < 20:
                    return None

                # Convert to DataFrame
                # HL candle format: {'T': timestamp_ms, 'o': open, 'h': high, 'l': low, 'c': close, 'v': volume, ...}
                rows = []
                for candle in data:
                    rows.append({
                        'timestamp': candle['T'],
                        'open': float(candle['o']),
                        'high': float(candle['h']),
                        'low': float(candle['l']),
                        'close': float(candle['c']),
                        'volume': float(candle['v']),
                    })

                df = pd.DataFrame(rows)
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

                # Validate
                if (df['close'] <= 0).any():
                    return None

                # Trim to limit
                if len(df) > limit:
                    df = df.tail(limit).reset_index(drop=True)

                return df

            except Exception as e:
                err_str = str(e)
                if 'timed out' in err_str.lower() or 'timeout' in err_str.lower():
                    wait_time = 5 * (attempt + 1)
                    log.warning(f"⏱️ Timeout {symbol} {timeframe}: {e}. Retry in {wait_time}s (Attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    log.warning(f"OHLCV fetch failed {symbol} {timeframe}: {e}")
                    return None

        log.error(f"❌ Failed to fetch OHLCV for {symbol} after {max_retries} retries.")
        return None

    def _calculate_correlation(self, coin_df: pd.DataFrame, btc_df: pd.DataFrame) -> float:
        """Calculate Pearson correlation of returns."""
        try:
            combined = pd.merge(
                coin_df[['timestamp', 'close']].rename(columns={'close': 'coin'}),
                btc_df[['timestamp', 'close']].rename(columns={'close': 'btc'}),
                on='timestamp'
            ).tail(DECOUPLING_WINDOW_H)

            if len(combined) < 12:
                return 1.0

            returns = combined[['coin', 'btc']].pct_change().dropna()
            corr = returns['coin'].corr(returns['btc'])
            return corr if not pd.isna(corr) else 1.0
        except Exception:
            return 1.0

    def fetch_multi_timeframe(self, symbol: str) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch OHLCV for all configured timeframes."""
        result = {}
        for tf in TIMEFRAMES:
            result[tf] = self.fetch_ohlcv(symbol, tf)
        result['1d'] = self.fetch_ohlcv(symbol, '1d', limit=50)
        result['15m'] = self.fetch_ohlcv(symbol, '15m', limit=100)
        return result

    def close(self):
        """Cleanup."""
        pass  # No persistent connections to close
