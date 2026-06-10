"""
ATLAS — Geopolitical & Conflict Intelligence (was KRON)
Has seen every playbook before. Nothing surprises him.
Watches political risk in EM/frontier markets.
"""
import logging
import feedparser
import httpx
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class AtlasAgent(BaseAgent):
    name = 'ATLAS'
    display_name = 'Atlas'
    personality = 'Has seen every playbook before. Nothing surprises him. Speaks like someone who has watched empires fall.'
    domain_context = (
        'Geopolitical and political risk intelligence for frontier and emerging markets. '
        'Watch: political instability, elections, coups, sanctions, debt restructuring, '
        'diplomatic shifts affecting Sub-Saharan Africa, MENA, Southeast Asia. '
        'Flag: regime change risk, sanctions announcements, IMF negotiations, '
        'election violence, currency controls, capital flight restrictions. '
        'Frame: investment risk, asset expropriation risk, market access risk for frontier funds.'
    )
    interval_minutes = 30

    def fetch_data(self) -> list:
        items = []
        feeds = [
            ('https://feeds.bbci.co.uk/news/world/africa/rss.xml', 'bbc_africa'),
            ('https://feeds.bbci.co.uk/news/world/asia/rss.xml', 'bbc_asia'),
            ('https://rss.dw.com/rdf/rss-en-africa', 'dw_africa'),
            ('https://www.voanews.com/api/zmgqpemvei', 'voa_africa'),
        ]
        for url, source in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    items.append({
                        'source': source,
                        'type': 'geopolitical_news',
                        'title': entry.get('title', ''),
                        'summary': entry.get('summary', '')[:400],
                        'url': entry.get('link', ''),
                        'published': entry.get('published', ''),
                    })
            except Exception as e:
                logger.debug(f"[ATLAS] Feed {source}: {e}")

        try:
            resp = httpx.get(
                'https://api.gdeltproject.org/api/v2/doc/doc?query=africa+instability&mode=artlist&maxrecords=10&format=json',
                timeout=12, headers={'User-Agent': 'AlphaOps/1.0'}
            )
            if resp.status_code == 200:
                data = resp.json()
                for article in data.get('articles', [])[:5]:
                    items.append({
                        'source': 'gdelt',
                        'type': 'conflict_signal',
                        'title': article.get('title', ''),
                        'url': article.get('url', ''),
                        'tone': article.get('tone', 0),
                    })
        except Exception as e:
            logger.debug(f"[ATLAS] GDELT error: {e}")

        return items


"""
WATT — Energy & Infrastructure Intelligence
Thinks in grids and flows. Believes energy is the only real story.
"""


class WattAgent(BaseAgent):
    name = 'WATT'
    display_name = 'Watt'
    personality = 'Energy obsessive. Thinks in grids and flows. Believes energy is the only real story and everything else is a subplot.'
    domain_context = (
        'Energy and infrastructure intelligence for emerging markets. '
        'Watch: oil production disruptions in Nigeria, Angola, Iraq; '
        'natural gas supply changes; power grid failures in EM cities; '
        'renewable energy project announcements in Africa/Asia; '
        'LNG terminal disruptions; pipeline attacks or shutdowns. '
        'Flag: energy supply shocks in EM manufacturing hubs, '
        'electricity crises affecting industrial output. '
        'Frame: energy infrastructure as the chokepoint for EM economic growth.'
    )
    interval_minutes = 60

    def fetch_data(self) -> list:
        items = []
        feeds = [
            ('https://www.eia.gov/rss/press_releases.xml', 'eia_press'),
            ('https://feeds.feedburner.com/oilprice-latest-energy-news', 'oilprice'),
            ('https://www.energymonitor.ai/feed', 'energy_monitor'),
        ]
        for url, source in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:4]:
                    items.append({
                        'source': source,
                        'type': 'energy_signal',
                        'title': entry.get('title', ''),
                        'summary': entry.get('summary', '')[:300],
                        'url': entry.get('link', ''),
                    })
            except Exception as e:
                logger.debug(f"[WATT] Feed {source}: {e}")

        eia_key = os.getenv('EIA_API_KEY', '')
        if eia_key:
            try:
                import os as _os
                resp = httpx.get(
                    'https://api.eia.gov/v2/petroleum/pri/spt/data/',
                    params={'api_key': eia_key, 'frequency': 'weekly', 'length': 4},
                    timeout=10
                )
                if resp.status_code == 200:
                    items.append({
                        'source': 'eia_api',
                        'type': 'energy_price',
                        'title': 'EIA Weekly Petroleum Prices Update',
                        'url': 'https://www.eia.gov/petroleum/prices.php',
                        'data': str(resp.json())[:500],
                    })
            except Exception as e:
                logger.debug(f"[WATT] EIA API: {e}")

        return items


import os


"""
TIDE — Maritime & Trade Route Intelligence (was HULL/DRAKE)
Thinks the ocean tells you everything six weeks before land does.
"""


class TideAgent(BaseAgent):
    name = 'TIDE'
    display_name = 'Tide'
    personality = 'Maritime and trade routes. Reads shipping lanes the way a sailor reads the sky. Patient, precise. Never wrong about direction, only about timing.'
    domain_context = (
        'Maritime and trade route intelligence for emerging market supply chains. '
        'Watch: Port of Mombasa, Dar es Salaam, Lagos, Colombo, Ho Chi Minh City, '
        'Chittagong, Karachi — congestion, delays, strikes. '
        'Flag: Red Sea routing disruptions, Suez Canal delays, '
        'African port strikes, AIS vessel anomalies, shipping rate spikes. '
        'Connect: shipping disruption → supply chain delay → commodity price pressure → EM inflation. '
        'Frame: who gets hurt when the containers stop moving.'
    )
    interval_minutes = 50

    def fetch_data(self) -> list:
        items = []
        feeds = [
            ('https://www.lloydslist.com/rss', 'lloyds_list'),
            ('https://www.porttechnology.org/feed/', 'port_technology'),
            ('https://splash247.com/feed/', 'splash247'),
        ]
        for url, source in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    items.append({
                        'source': source,
                        'type': 'maritime_signal',
                        'title': entry.get('title', ''),
                        'summary': entry.get('summary', '')[:300],
                        'url': entry.get('link', ''),
                    })
            except Exception as e:
                logger.debug(f"[TIDE] Feed {source}: {e}")

        try:
            resp = httpx.get(
                'https://www.balticexchange.com/api/v1/indices',
                timeout=10, headers={'User-Agent': 'AlphaOps/1.0'}
            )
            if resp.status_code == 200:
                items.append({
                    'source': 'baltic_exchange',
                    'type': 'shipping_rates',
                    'title': 'Baltic Exchange Shipping Indices — current rates',
                    'url': 'https://www.balticexchange.com/en/index.html',
                    'data': str(resp.json())[:400],
                })
        except Exception as e:
            logger.debug(f"[TIDE] Baltic Exchange: {e}")

        return items


"""
ECHO — Social Sentiment & Narrative Intelligence (was PULSE)
Listens to the noise of the internet the way a doctor listens to a heartbeat.
"""


class EchoAgent(BaseAgent):
    name = 'ECHO'
    display_name = 'Echo'
    personality = 'Listens to the noise of the internet the way a doctor listens to a heartbeat. Finds the signal in collective human anxiety.'
    domain_context = (
        'Social sentiment and narrative intelligence for emerging markets. '
        'Watch: Reddit EM investing communities, Twitter/X trending in EM countries, '
        'Mastodon economic discussions, HackerNews threads on EM tech. '
        'Flag: narrative shifts before mainstream media, '
        'social unrest signals, viral economic anxiety in EM populations, '
        'cross-platform convergence on same EM topic. '
        'Frame: what collective intelligence is saying before institutional analysts catch it.'
    )
    interval_minutes = 40

    def fetch_data(self) -> list:
        items = []
        reddit_feeds = [
            ('https://www.reddit.com/r/emergingmarkets/.rss?limit=10', 'reddit_em'),
            ('https://www.reddit.com/r/africafinance/.rss?limit=10', 'reddit_africa_finance'),
            ('https://www.reddit.com/r/investing/search.rss?q=emerging+markets&sort=new', 'reddit_investing_em'),
        ]
        headers = {'User-Agent': 'AlphaOps:v1.0 (intelligence platform)'}
        for url, source in reddit_feeds:
            try:
                resp = httpx.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    feed = feedparser.parse(resp.text)
                    for entry in feed.entries[:4]:
                        items.append({
                            'source': source,
                            'type': 'social_signal',
                            'title': entry.get('title', ''),
                            'summary': entry.get('summary', '')[:300],
                            'url': entry.get('link', ''),
                        })
            except Exception as e:
                logger.debug(f"[ECHO] Reddit {source}: {e}")

        hn_feeds = [
            'https://hnrss.org/newest?q=africa+investment&count=5',
            'https://hnrss.org/newest?q=emerging+markets&count=5',
        ]
        for url in hn_feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]:
                    items.append({
                        'source': 'hackernews',
                        'type': 'tech_community_signal',
                        'title': entry.get('title', ''),
                        'url': entry.get('link', ''),
                        'points': entry.get('comments', 0),
                    })
            except Exception as e:
                logger.debug(f"[ECHO] HN: {e}")

        return items


"""
LEX — Regulatory & Legal Intelligence (was STATUTE)
Finds the one sentence in a 200-page bill that changes everything.
"""


class LexAgent(BaseAgent):
    name = 'LEX'
    display_name = 'Lex'
    personality = 'Regulatory and legal. Dry, precise, devastating. Finds the one sentence in a 200-page bill that changes everything.'
    domain_context = (
        'Regulatory and legal intelligence for emerging market investments. '
        'Watch: sanctions announcements (OFAC, EU, UN), IMF program changes, '
        'World Bank country reports, EM central bank policy decisions, '
        'mining and resource licensing changes in Africa/Asia, '
        'trade agreement developments affecting EM economies. '
        'Flag: sanctions that freeze assets, regulatory changes that affect market access, '
        'IMF conditionality changes, currency control announcements. '
        'Frame: legal risk for investors, compliance requirements, market access changes.'
    )
    interval_minutes = 55

    def fetch_data(self) -> list:
        items = []
        feeds = [
            ('https://www.imf.org/en/News/RSS?language=eng&category=PRandNews', 'imf_news'),
            ('https://www.worldbank.org/en/news/all.rss', 'world_bank'),
            ('https://home.treasury.gov/system/files/126/ofac_press.xml', 'ofac_sanctions'),
        ]
        for url, source in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    items.append({
                        'source': source,
                        'type': 'regulatory_signal',
                        'title': entry.get('title', ''),
                        'summary': entry.get('summary', '')[:400],
                        'url': entry.get('link', ''),
                        'published': entry.get('published', ''),
                    })
            except Exception as e:
                logger.debug(f"[LEX] Feed {source}: {e}")

        return items
