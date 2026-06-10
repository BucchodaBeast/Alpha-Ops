"""
VOSS — Insider & Dark Pool Intelligence
Ex-compliance officer turned poacher. Reads SEC filings, insider moves.
Sees manipulation in everything because he used to do it.
"""
import logging
import feedparser
import httpx
from datetime import datetime, timezone
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class VossAgent(BaseAgent):
    name = 'VOSS'
    display_name = 'Voss'
    personality = 'Ex-compliance officer turned poacher. Sees manipulation in everything because he used to do it. Paranoid. Always right eventually.'
    domain_context = (
        'Insider trading detection and dark money flow intelligence for emerging markets. '
        'Watch: SEC Form 4 filings (insider buys/sells in EM-exposed companies), '
        'FINRA short interest in frontier market ETFs and commodity companies, '
        'unusual options activity in companies with significant EM exposure '
        '(mining, energy, logistics, agriculture). '
        'Flag: cluster buys before announcements, unusual put/call ratios, '
        'mass insider selling in Africa/Asia-exposed stocks. '
        'Frame: who is positioning and why before the news breaks.'
    )
    interval_minutes = 35

    def fetch_data(self) -> list:
        items = []
        items.extend(self._fetch_sec_insider())
        items.extend(self._fetch_finra())
        items.extend(self._fetch_em_etf_flows())
        return items

    def _fetch_sec_insider(self) -> list:
        items = []
        try:
            feed = feedparser.parse(
                'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent'
                '&type=4&company=&dateb=&owner=only&count=40&output=atom'
            )
            for entry in feed.entries[:12]:
                title = entry.get('title', '')
                items.append({
                    'source': 'sec_edgar',
                    'type': 'insider_filing',
                    'title': title,
                    'company': title.split(' - ')[0] if ' - ' in title else title,
                    'filing_date': entry.get('updated', ''),
                    'url': entry.get('link', ''),
                    'context': 'SEC Form 4 — insider transaction disclosure',
                })
        except Exception as e:
            logger.warning(f"[VOSS] SEC feed error: {e}")
        return items

    def _fetch_finra(self) -> list:
        items = []
        try:
            resp = httpx.get(
                'https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data',
                timeout=10, headers={'User-Agent': 'AlphaOps/1.0'}
            )
            if resp.status_code == 200:
                items.append({
                    'source': 'finra',
                    'type': 'short_interest_summary',
                    'title': 'FINRA short sale volume data — current period',
                    'note': 'FINRA short interest updated. Scan for elevated short positions in EM-exposed equities.',
                    'url': 'https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data',
                })
        except Exception as e:
            logger.warning(f"[VOSS] FINRA error: {e}")
        return items

    def _fetch_em_etf_flows(self) -> list:
        """Monitor EM ETF flows as capital movement proxy"""
        import httpx
        # EM-focused ETFs: EEM, VWO, FM (frontier markets), AFK (Africa)
        etfs = ['EEM', 'VWO', 'FM', 'AFK', 'EEMV']
        items = []
        for etf in etfs:
            try:
                resp = httpx.get(
                    f'https://query1.finance.yahoo.com/v8/finance/chart/{etf}?interval=1d&range=5d',
                    headers={'User-Agent': 'Mozilla/5.0'}, timeout=8
                )
                if resp.is_success:
                    meta = resp.json().get('chart', {}).get('result', [{}])[0].get('meta', {})
                    price = meta.get('regularMarketPrice', 0)
                    prev = meta.get('previousClose', price)
                    vol = meta.get('regularMarketVolume', 0)
                    avg_vol = meta.get('averageDailyVolume10Day', vol)
                    chg = round((price - prev) / prev * 100, 2) if prev else 0
                    vol_ratio = round(vol / max(avg_vol, 1), 2) if avg_vol else 1.0
                    if abs(chg) > 0.5 or vol_ratio > 1.3:  # Only flag notable moves
                        items.append({
                            'source': 'yahoo_finance',
                            'type': 'etf_flow',
                            'ticker': etf,
                            'title': f"{etf} ETF: ${price:.2f} ({chg:+.2f}%) — Vol ratio {vol_ratio}x",
                            'price': price, 'change_pct': chg,
                            'volume_ratio': vol_ratio,
                            'unusual_volume': vol_ratio > 1.5,
                            'url': f'https://finance.yahoo.com/quote/{etf}',
                            'em_context': f'{etf} tracks emerging/frontier market equities — flow signals institutional positioning',
                        })
            except Exception as e:
                logger.debug(f"[VOSS] ETF {etf}: {e}")
        return items
