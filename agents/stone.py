"""
STONE — Markets & Currency Intelligence
Old school. Reads frontier markets like weather.
Watches EM currencies, commodity prices, capital flow signals.
"""
import os
import logging
from datetime import datetime, timezone
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class StoneAgent(BaseAgent):
    name = 'STONE'
    display_name = 'Stone'
    personality = 'Old school. Reads frontier markets like weather. Been wrong twice in 20 years and remembers both times. Speaks in short declarative sentences.'
    domain_context = (
        'Frontier and emerging market financial intelligence. '
        'Watch: EM currency movements (NGN, KES, IDR, VND, BDT, PKR), '
        'commodity prices affecting EM economies (oil, copper, cocoa, palm oil, wheat), '
        'capital flow signals, crypto as EM capital flight proxy. '
        'Flag: currency stress, unusual volume, spread widening, capital flight patterns. '
        'Frame for frontier fund managers and commodity traders.'
    )
    interval_minutes = 20

    def fetch_data(self) -> list:
        items = []
        items.extend(self._fetch_kraken())
        items.extend(self._fetch_commodities())
        items.extend(self._fetch_fred())
        return items

    def _fetch_kraken(self) -> list:
        import httpx
        # BTC/ETH as capital flight proxies + major EM-relevant pairs
        pairs = ['XBTUSD', 'XETHZUSD', 'SOLUSD']
        items = []
        try:
            resp = httpx.get(
                'https://api.kraken.com/0/public/Ticker',
                params={'pair': ','.join(pairs)},
                headers={'User-Agent': 'AlphaOps/1.0'},
                timeout=12,
            )
            if not resp.is_success:
                return []
            name_map = {
                'XXBTZUSD': ('Bitcoin', 'BTC'), 'XBTUSD': ('Bitcoin', 'BTC'),
                'XETHZUSD': ('Ethereum', 'ETH'), 'SOLUSD': ('Solana', 'SOL'),
            }
            for pair_id, ticker in resp.json().get('result', {}).items():
                name, sym = name_map.get(pair_id, (pair_id, pair_id[:3]))
                try:
                    last = float(ticker['c'][0])
                    open_ = float(ticker['o'])
                    high = float(ticker['h'][1])
                    low = float(ticker['l'][1])
                    vol_24h = float(ticker['v'][1])
                    vol_today = float(ticker['v'][0])
                    chg = round((last - open_) / open_ * 100, 2) if open_ else 0
                    vol_ratio = round(vol_today / max(vol_24h, 1) * 24, 2) if vol_24h else 1.0
                    items.append({
                        'source': 'kraken', 'ticker': sym,
                        'title': f"{name} ({sym}): ${last:,.2f} ({chg:+.2f}%)",
                        'price': round(last, 2), 'change_pct': chg,
                        'high_24h': round(high, 2), 'low_24h': round(low, 2),
                        'volume_24h': round(vol_24h, 2), 'volume_ratio': vol_ratio,
                        'unusual_volume': vol_ratio > 1.5,
                        'url': f'https://www.kraken.com/prices/{name.lower()}',
                        'em_context': 'Capital flight proxy — EM investors use crypto to move money across borders',
                    })
                except Exception as e:
                    logger.debug(f"[STONE] Kraken parse {pair_id}: {e}")
        except Exception as e:
            logger.warning(f"[STONE] Kraken failed: {e}")
        return items

    def _fetch_commodities(self) -> list:
        """Fetch commodity prices via open APIs - critical for EM economies"""
        import httpx
        items = []
        # Open Exchange Rates free tier (metals/oil proxies via public feeds)
        commodity_feeds = [
            ('https://query1.finance.yahoo.com/v8/finance/chart/CL=F?interval=1d&range=2d', 'Crude Oil WTI', 'OIL'),
            ('https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=2d', 'Gold', 'GOLD'),
            ('https://query1.finance.yahoo.com/v8/finance/chart/HG=F?interval=1d&range=2d', 'Copper', 'COPPER'),
        ]
        for url, name, sym in commodity_feeds:
            try:
                resp = httpx.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                if resp.is_success:
                    data = resp.json()
                    meta = data.get('chart', {}).get('result', [{}])[0].get('meta', {})
                    price = meta.get('regularMarketPrice', 0)
                    prev = meta.get('previousClose', price)
                    chg = round((price - prev) / prev * 100, 2) if prev else 0
                    items.append({
                        'source': 'yahoo_finance', 'ticker': sym,
                        'title': f"{name}: ${price:.2f} ({chg:+.2f}%)",
                        'price': round(price, 2), 'change_pct': chg,
                        'url': f'https://finance.yahoo.com/quote/{sym}=F',
                        'em_relevance': f"{name} price directly impacts EM economies",
                    })
            except Exception as e:
                logger.debug(f"[STONE] Commodity {sym} failed: {e}")
        return items

    def _fetch_fred(self) -> list:
        import httpx
        fred_key = os.getenv('FRED_API_KEY', '')
        if not fred_key:
            return []
        series = [
            ('DTWEXBGS', 'USD Broad Trade-Weighted Index'),
            ('T10Y2Y', '10Y-2Y Treasury Spread'),
        ]
        items = []
        for sid, label in series:
            try:
                resp = httpx.get(
                    'https://api.stlouisfed.org/fred/series/observations',
                    params={'series_id': sid, 'api_key': fred_key,
                            'file_type': 'json', 'limit': 2, 'sort_order': 'desc'},
                    timeout=10,
                )
                if resp.status_code == 200:
                    obs = resp.json().get('observations', [])
                    if obs and obs[0]['value'] != '.':
                        curr = float(obs[0]['value'])
                        prev = float(obs[1]['value']) if len(obs) > 1 and obs[1]['value'] != '.' else curr
                        items.append({
                            'source': 'fred', 'series': sid,
                            'title': f"FRED {label}: {curr} ({curr - prev:+.3f} vs prior)",
                            'value': curr, 'change': round(curr - prev, 4),
                            'url': f'https://fred.stlouisfed.org/series/{sid}',
                            'em_context': 'Strong USD increases EM debt pressure and capital outflows',
                        })
            except Exception as e:
                logger.debug(f"[STONE] FRED {sid}: {e}")
        return items
