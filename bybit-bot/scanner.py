"""
Bybit Crypto Algo Bot — Market Scanner
Scans all Bybit USDT perpetual coins, detects Alpha (KALIMASADA-style).
"""
import time
import logging
import ccxt
import pandas as pd
from typing import List, Dict, Optional
from config import (
    BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET,
    TIMEFRAMES, CANDLE_LOOKBACK,
    STOCH_ENTRY_MIN, STOCH_ENTRY_MAX, SL_BUFFER_PCT, DEFAULT_RR_RATIO,
    ALPHA_THRESHOLD_PCT, ALPHA_LOOKBACK_H, ALPHA_CANDIDATE_LIMIT,
    MAX_ALPHA_COINS, RATE_LIMIT_DELAY, MIN_VOLUME_24H, MIN_PRICE,
    MAX_SPREAD_PCT, BLACKLIST_SYMBOLS, VOLUME_ALPHA_THRESHOLD,
    BTC_VOLUME_MAX_RATIO, DECOUPLING_THRESHOLD, DECOUPLING_WINDOW_H,
    NEW_LISTING_DAYS
)

log = logging.getLogger('scanner')


class MarketScanner:
    """Scans all Bybit USDT Perpetual markets for Alpha coins."""

    def __init__(self):
        config = {
            'options': {'defaultType': 'swap'},
            'enableRateLimit': True,
        }
        if BYBIT_API_KEY:
            config['apiKey'] = BYBIT_API_KEY
            config['secret'] = BYBIT_API_SECRET

        self.exchange = ccxt.bybit(config)

        if BYBIT_TESTNET:
            self.exchange.set_sandbox_mode(True)
            log.info("Scanner: TESTNET mode enabled")

        self.markets_info: Dict[str, Dict] = {}
        self._markets_loaded = False

    def load_markets(self):
        """Load all USDT linear perpetual markets from Bybit."""
        try:
            markets = self.exchange.load_markets()
            self.markets_info = {}

            for symbol, info in markets.items():
                if not (info.get('linear') and
                        info.get('active') and
                        info.get('settle') == 'USDT' and
                        info.get('type') == 'swap'):
                    continue
                if symbol in BLACKLIST_SYMBOLS:
                    continue

                limits = info.get('limits', {})
                amount_limits = limits.get('amount', {})
                cost_limits = limits.get('cost', {})
                precision = info.get('precision', {})

                self.markets_info[symbol] = {
                    'id': info['id'],                    # e.g. 'BTCUSDT'
                    'symbol': symbol,                    # e.g. 'BTC/USDT:USDT'
                    'base': info.get('base', ''),
                    'min_qty': amount_limits.get('min', 0.001),
                    'qty_step': precision.get('amount', 0.001),
                    'min_notional': cost_limits.get('min', 1.0),
                    'price_precision': precision.get('price', 0.01),
                }

            self._markets_loaded = True
            log.info(f"Loaded {len(self.markets_info)} USDT perpetual markets")

        except Exception as e:
            log.error(f"Failed to load markets: {e}")
            raise

    def get_market_info(self, symbol: str) -> Optional[Dict]:
        """Get market info for a symbol."""
        return self.markets_info.get(symbol)

    def _get_pct_change(self, symbol: str, lookback_h: int) -> float:
        """Calculate price percentage change over the last X hours."""
        try:
            # 4h timeframe is best for "Institutional Alpha"
            # If lookback is 4h, we need at least 2 candles of 4h, or 4 candles of 1h
            tf = '1h'
            df = self.fetch_ohlcv(symbol, tf, limit=lookback_h + 1)
            if df is None or len(df) < lookback_h:
                return 0.0
            
            start_price = df['close'].iloc[0]
            end_price = df['close'].iloc[-1]
            return ((end_price - start_price) / start_price) * 100
        except Exception:
            return 0.0

    def scan_for_alpha(self) -> List[Dict]:
        """
        KALIMASADA-style Alpha scan:
        1. Fetch all tickers (24h) as a broad filter
        2. Filter down to top candidates (ALPHA_CANDIDATE_LIMIT)
        3. Deep-scan candidates for real-time 4h Alpha vs BTC
        4. Sort by real-time alpha strength
        """
        if not self._markets_loaded:
            self.load_markets()

        try:
            tickers = self.exchange.fetch_tickers()
        except Exception as e:
            log.error(f"Failed to fetch tickers: {e}")
            return []

        # Get BTC benchmark (4h real-time)
        btc_df = self.fetch_ohlcv('BTC/USDT:USDT', '1h', limit=DECOUPLING_WINDOW_H + 1)
        if btc_df is None or len(btc_df) < 5:
            log.warning("Scanner: Failed to fetch BTC benchmark data.")
            return []

        # 4h change (from 1h data)
        btc_start_4h = btc_df['close'].iloc[-5] if len(btc_df) >= 5 else btc_df['close'].iloc[0]
        btc_now = btc_df['close'].iloc[-1]
        btc_change_4h = ((btc_now - btc_start_4h) / btc_start_4h) * 100
        
        # BTC Volume Ratio (last 4h vs last 24h)
        btc_vol_recent = btc_df['volume'].iloc[-4:].mean()
        btc_vol_avg = btc_df['volume'].mean()
        btc_vol_ratio = btc_vol_recent / btc_vol_avg if btc_vol_avg > 0 else 1.0

        log.info(f"BTC {ALPHA_LOOKBACK_H}h change: {btc_change_4h:+.2f}% | Vol Ratio: {btc_vol_ratio:.2f}x")

        candidates = []

        for symbol, ticker in tickers.items():
            if symbol not in self.markets_info:
                continue

            try:
                vol_24h = float(ticker.get('quoteVolume', 0) or 0)
                last_price = float(ticker.get('last', 0) or 0)
                pct_change_24h = float(ticker.get('percentage', 0) or 0)

                # Broad Filter: Min volume and Price
                if vol_24h < MIN_VOLUME_24H or last_price < MIN_PRICE:
                    continue
                
                # Alpha proxy (24h) for initial sorting
                alpha_24h = pct_change_24h - (btc_change_4h if btc_change_4h else 0)
                
                candidates.append({
                    'symbol': symbol,
                    'ticker': ticker,
                    'alpha_24h_proxy': alpha_24h
                })

            except (TypeError, ValueError):
                continue

        # Sort by 24h proxy to find top candidates for deep scan
        candidates.sort(key=lambda x: x['alpha_24h_proxy'], reverse=True)
        top_candidates = candidates[:ALPHA_CANDIDATE_LIMIT]

        alpha_coins = []
        log.info(f"Deep scanning {len(top_candidates)} candidates for {ALPHA_LOOKBACK_H}h Alpha...")

        for item in top_candidates:
            symbol = item['symbol']
            ticker = item['ticker']
            info = self.get_market_info(symbol)
            if not info:
                continue
            
            # Deep Scan Logic
            coin_df = self.fetch_ohlcv(symbol, '1h', limit=DECOUPLING_WINDOW_H + 1)
            if coin_df is None or len(coin_df) < 5:
                continue

            # 1. Absolute Return Guard (Must be > 0% while BTC is whatever)
            # This filters out coins that are just "falling slower" than BTC.
            price_start = coin_df['close'].iloc[-5]
            price_now = coin_df['close'].iloc[-1]
            pct_change_4h = ((price_now - price_start) / price_start) * 100
            
            if pct_change_4h <= 0:
                continue # REJECT: Not absolute green

            # 2. Alpha check
            alpha_4h = pct_change_4h - btc_change_4h
            if alpha_4h < ALPHA_THRESHOLD_PCT:
                continue

            # 3. Volume Alpha (Institutional Accumulation)
            # Coin volume surging while BTC is "dry"
            coin_vol_recent = coin_df['volume'].iloc[-4:].mean()
            coin_vol_avg = coin_df['volume'].mean()
            coin_vol_ratio = coin_vol_recent / coin_vol_avg if coin_vol_avg > 0 else 1.0
            
            is_volume_alpha = (coin_vol_ratio >= VOLUME_ALPHA_THRESHOLD) and (btc_vol_ratio <= BTC_VOLUME_MAX_RATIO)

            # 4. Decoupling Detector (Pearson Correlation)
            correlation = self._calculate_correlation(coin_df, btc_df)
            is_decoupled = correlation <= DECOUPLING_THRESHOLD
            
            # 5. New Listing Detection
            # If 1h history is less than NEW_LISTING_DAYS, it's 'New'
            # 24 candles per day * NEW_LISTING_DAYS
            history_len = len(coin_df)
            is_new_listing = history_len <= (NEW_LISTING_DAYS * 24)

            # Bid/Ask for spread check
            bid = float(ticker.get('bid', 0) or 0)
            ask = float(ticker.get('ask', 0) or 0)
            spread_pct = ((ask - bid) / bid) * 100 if bid > 0 else 0
            
            if spread_pct > MAX_SPREAD_PCT:
                continue

            alpha_coins.append({
                'symbol': symbol,
                'bybit_symbol': info['id'],
                'base': info['base'],
                'price': float(price_now),
                'volume_24h': float(ticker.get('quoteVolume', 0)),
                'pct_change_24h': float(ticker.get('percentage', 0)),
                'pct_change_4h': float(round(pct_change_4h, 2)),
                'btc_change_4h': float(round(btc_change_4h, 2)),
                'alpha': float(round(alpha_4h, 2)),
                'spread_pct': float(round(spread_pct, 4)),
                'market_info': info,
                'is_volume_alpha': bool(is_volume_alpha),
                'is_decoupled': bool(is_decoupled),
                'is_new_listing': bool(is_new_listing),
                'correlation': float(round(correlation, 3)),
                'vol_ratio': float(round(coin_vol_ratio, 2))
            })

        # Final Sort by REAL-TIME alpha (4h)
        alpha_coins.sort(key=lambda x: x['alpha'], reverse=True)
        result = alpha_coins[:MAX_ALPHA_COINS]

        log.info(f"Alpha scan finished: {len(alpha_coins)} alpha found → top {len(result)} selected")

        if result:
            top3 = ', '.join([f"{c['base']}({c['alpha']:+.1f}%)" for c in result[:3]])
            log.info(f"Top 4h Alpha: {top3}")

        return result

    def scan_top_volume(self) -> List[Dict]:
        """
        Scan top 60 coins by 24h volume — TANPA filter alpha/pump.
        Ini meniru cara v6 backtest: scan SEMUA koin, biarkan analyze()
        yang menentukan apakah ada ascending triangle pattern.
        
        Koin yang sudah pump TETAP bisa masuk (pucuk filter di main.py
        yang akan handle), dan koin yang BELUM pump juga masuk —
        ini yang penting karena ascending triangle terbentuk SEBELUM pump.
        """
        if not self._markets_loaded:
            self.load_markets()

        try:
            tickers = self.exchange.fetch_tickers()
        except Exception as e:
            log.warning(f"Failed to fetch tickers for volume scan: {e}")
            return []

        candidates = []
        for symbol, ticker in tickers.items():
            if symbol not in self.markets_info:
                continue
            try:
                vol_24h = float(ticker.get('quoteVolume', 0) or 0)
                last_price = float(ticker.get('last', 0) or 0)
                base = self.markets_info[symbol].get('base', symbol.split('/')[0])

                if vol_24h < MIN_VOLUME_24H or last_price < MIN_PRICE:
                    continue
                if symbol in BLACKLIST_SYMBOLS:
                    continue

                bid = float(ticker.get('bid', 0) or 0)
                ask = float(ticker.get('ask', 0) or 0)
                spread_pct = ((ask - bid) / bid) * 100 if bid > 0 else 0
                if spread_pct > MAX_SPREAD_PCT:
                    continue

                candidates.append({
                    'symbol': symbol,
                    'bybit_symbol': self.markets_info[symbol].get('id', symbol),
                    'base': base,
                    'price': last_price,
                    'volume_24h': vol_24h,
                    'pct_change_24h': float(ticker.get('percentage', 0) or 0),
                    'spread_pct': round(spread_pct, 4),
                    'market_info': self.markets_info[symbol],
                    'alpha': 0.0,
                    'is_volume_alpha': False,
                    'is_decoupled': False,
                    'is_new_listing': False,
                    'correlation': 1.0,
                    'vol_ratio': 1.0,
                })
            except (TypeError, ValueError):
                continue

        # Sort by volume descending — ambil top 60 (mirip v6 backtest 63 koin)
        candidates.sort(key=lambda x: x['volume_24h'], reverse=True)
        result = candidates[:60]

        log.info(f"Volume scan: {len(candidates)} candidates → top {len(result)} by volume")
        if result:
            top3 = ', '.join([f"{c['base']}(${c['volume_24h']/1e6:.0f}M)" for c in result[:3]])
            log.info(f"Top volume: {top3}")

        return result

    def fetch_ohlcv(self, symbol: str, timeframe: str,
                    limit: int = CANDLE_LOOKBACK) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV candlestick data as a clean DataFrame.
        Returns None if fetch fails.
        """
        try:
            time.sleep(RATE_LIMIT_DELAY)  # Rate limit protection
            data = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

            if not data or len(data) < 20:
                return None

            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high',
                                             'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)

            # Validate: no zero prices
            if (df['close'] <= 0).any():
                return None

            return df

        except Exception as e:
            log.warning(f"OHLCV fetch failed {symbol} {timeframe}: {e}")
            return None

    def _calculate_correlation(self, coin_df: pd.DataFrame, btc_df: pd.DataFrame) -> float:
        """Calculate Pearson correlation of returns over 24h window."""
        try:
            # Align by timestamp
            combined = pd.merge(
                coin_df[['timestamp', 'close']].rename(columns={'close': 'coin'}),
                btc_df[['timestamp', 'close']].rename(columns={'close': 'btc'}),
                on='timestamp'
            ).tail(DECOUPLING_WINDOW_H)

            if len(combined) < 12:
                return 1.0  # High correlation filter if not enough data

            # Calculate pct returns
            returns = combined[['coin', 'btc']].pct_change().dropna()
            
            # Pearson correlation
            corr = returns['coin'].corr(returns['btc'])
            return corr if not pd.isna(corr) else 1.0
        except Exception:
            return 1.0

    def fetch_multi_timeframe(self, symbol: str) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch OHLCV for all configured timeframes + Daily for Pucuk Protector."""
        result = {}
        for tf in TIMEFRAMES:
            result[tf] = self.fetch_ohlcv(symbol, tf)
        # Always fetch Daily for Pucuk Protector & Structure Validator
        result['1d'] = self.fetch_ohlcv(symbol, '1d', limit=50)
        return result

    def close(self):
        """Cleanup exchange connection."""
        try:
            self.exchange.close()
        except Exception:
            pass
