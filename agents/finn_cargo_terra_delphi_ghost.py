"""
FINN — Opportunity & Investment Signal Intelligence (was SCOUT)
Restless. Sees the opportunity before the company announces the pivot. Always early.
Watches EM investment flows, startup activity, hiring signals.
"""
import logging
import feedparser
import httpx
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class FinnAgent(BaseAgent):
    name = 'FINN'
    display_name = 'Finn'
    personality = 'Opportunity hunter. Restless. Sees the job posting before the company announces the pivot. Always early.'
    domain_context = (
        'Investment opportunity and capital flow intelligence for emerging markets. '
        'Watch: PE/VC deals in Africa and Southeast Asia, DFI (development finance) '
        'announcements, World Bank/IFC project approvals, startup funding rounds in EM, '
        'hiring surges at EM-focused investment firms. '
        'Flag: first-mover signals — when smart money moves into a market before it\'s obvious, '
        'infrastructure investment announcements, new market entry signals. '
        'Frame: where is the next capital flow going, and who is positioning for it.'
    )
    interval_minutes = 75

    def fetch_data(self) -> list:
        items = []
        feeds = [
            ('https://disrupt-africa.com/feed/', 'disrupt_africa'),
            ('https://techpoint.africa/feed/', 'techpoint_africa'),
            ('https://www.ifc.org/wps/wcm/connect/news_ext_content/ifc_external_corporate_site/news+and+events/news/rss', 'ifc_deals'),
            ('https://techcrunch.com/category/asia/feed/', 'tc_asia'),
        ]
        for url, source in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    items.append({
                        'source': source,
                        'type': 'investment_signal',
                        'title': entry.get('title', ''),
                        'summary': entry.get('summary', '')[:350],
                        'url': entry.get('link', ''),
                        'published': entry.get('published', ''),
                    })
            except Exception as e:
                logger.debug(f"[FINN] Feed {source}: {e}")

        return items


"""
CARGO — Supply Chain Intelligence (was PARCEL)
Thinks in containers and routes. Knows a crisis is forming when the boxes stop moving.
"""


class CargoAgent(BaseAgent):
    name = 'CARGO'
    display_name = 'Cargo'
    personality = 'Supply chain. Thinks in containers and routes. Knows a crisis is forming when the boxes stop moving.'
    domain_context = (
        'Global supply chain intelligence focused on emerging market disruptions. '
        'Watch: manufacturing output changes in Vietnam, Bangladesh, Indonesia, India, '
        'garment industry disruptions, electronics supply chain shifts, '
        'agricultural commodity supply chain events. '
        'Flag: factory closures, labor strikes in EM manufacturing hubs, '
        'port congestion at key EM export points, shipping container shortages. '
        'Connect: supply chain event → delivery delays → inventory shortfalls → price impacts. '
        'Frame: what breaks where, and who bears the cost.'
    )
    interval_minutes = 65

    def fetch_data(self) -> list:
        items = []
        feeds = [
            ('https://www.freightwaves.com/news/feed', 'freightwaves'),
            ('https://www.supplychaindive.com/feeds/news/', 'supply_chain_dive'),
            ('https://www.just-style.com/feed/', 'just_style'),
        ]
        for url, source in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    items.append({
                        'source': source,
                        'type': 'supply_chain_signal',
                        'title': entry.get('title', ''),
                        'summary': entry.get('summary', '')[:350],
                        'url': entry.get('link', ''),
                    })
            except Exception as e:
                logger.debug(f"[CARGO] Feed {source}: {e}")

        return items


"""
TERRA — Climate & Environmental Intelligence (was GAIA)
Long memory. Connects weather patterns to political instability to food prices.
"""


class TerraAgent(BaseAgent):
    name = 'TERRA'
    display_name = 'Terra'
    personality = 'Climate and environment. Long memory. Connects weather patterns to political instability to food prices without breaking a sweat.'
    domain_context = (
        'Climate and environmental intelligence for emerging market risk. '
        'Watch: El Nino/La Nina forecasts affecting African/Asian agriculture, '
        'flood and drought alerts in food-producing EM regions, '
        'cyclone/typhoon paths over EM manufacturing and port cities, '
        'NOAA seasonal outlooks for tropical regions. '
        'Connect: drought in East Africa → food insecurity → political instability → capital flight. '
        'Connect: flooding in Bangladesh → garment factory shutdowns → supply chain delays. '
        'Frame: climate as the upstream cause of downstream investment risk.'
    )
    interval_minutes = 80

    def fetch_data(self) -> list:
        items = []
        feeds = [
            ('https://www.noaa.gov/news-release/feed', 'noaa'),
            ('https://reliefweb.int/updates/rss.xml?type[]=alert', 'reliefweb_alerts'),
            ('https://www.fao.org/news/rss-feed/en/', 'fao_food'),
            ('https://alerts.weather.gov/cap/us.php?x=0', 'noaa_alerts'),
        ]
        for url, source in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:4]:
                    items.append({
                        'source': source,
                        'type': 'climate_signal',
                        'title': entry.get('title', ''),
                        'summary': entry.get('summary', '')[:300],
                        'url': entry.get('link', ''),
                    })
            except Exception as e:
                logger.debug(f"[TERRA] Feed {source}: {e}")

        return items


"""
DELPHI — Prediction Market Intelligence (was ODDS/PASCAL)
Stopped being dramatic about seeing the future. Just numbers. Just odds.
"""


class DelphiAgent(BaseAgent):
    name = 'DELPHI'
    display_name = 'Delphi'
    personality = 'Has been asked to see the future so many times she stopped being dramatic about it. Just numbers. Just odds. Unnerving how calm she is when everything is on fire.'
    domain_context = (
        'Prediction market and probabilistic intelligence for emerging markets. '
        'Watch: Polymarket, Metaculus, Manifold — markets on EM elections, '
        'conflicts, economic outcomes, policy decisions. '
        'Flag: probability shifts on EM political events, '
        'market consensus vs analyst consensus divergence, '
        'implied probabilities on regime change, default risk, sanctions. '
        'Frame: what the crowd is pricing in that nobody is saying out loud.'
    )
    interval_minutes = 85

    def fetch_data(self) -> list:
        items = []
        try:
            resp = httpx.get(
                'https://gamma-api.polymarket.com/markets?closed=false&limit=20&tag=politics',
                timeout=12, headers={'User-Agent': 'AlphaOps/1.0'}
            )
            if resp.status_code == 200:
                markets = resp.json()
                em_keywords = ['africa', 'nigeria', 'kenya', 'ethiopia', 'ghana',
                               'indonesia', 'vietnam', 'india', 'pakistan', 'bangladesh',
                               'emerging', 'frontier', 'coup', 'election', 'imf', 'sanctions']
                for market in markets[:20]:
                    question = market.get('question', '').lower()
                    if any(kw in question for kw in em_keywords):
                        items.append({
                            'source': 'polymarket',
                            'type': 'prediction_market',
                            'title': market.get('question', ''),
                            'probability': market.get('outcomePrices', ['N/A'])[0],
                            'volume': market.get('volume', 0),
                            'url': f"https://polymarket.com/event/{market.get('slug', '')}",
                        })
        except Exception as e:
            logger.warning(f"[DELPHI] Polymarket error: {e}")

        try:
            resp = httpx.get(
                'https://www.metaculus.com/api2/questions/?order_by=-activity&limit=10&search=africa',
                timeout=12, headers={'User-Agent': 'AlphaOps/1.0'}
            )
            if resp.status_code == 200:
                for q in resp.json().get('results', [])[:5]:
                    items.append({
                        'source': 'metaculus',
                        'type': 'forecasting_question',
                        'title': q.get('title', ''),
                        'community_prediction': q.get('community_prediction', {}).get('full', {}).get('q2'),
                        'url': f"https://www.metaculus.com{q.get('page_url', '')}",
                    })
        except Exception as e:
            logger.debug(f"[DELPHI] Metaculus error: {e}")

        return items


"""
GHOST — Conflict & Instability Intelligence (was CIPHER)
Works in shadows. Reads GDELT like others read Twitter. Never loud, always right.
"""


class GhostAgent(BaseAgent):
    name = 'GHOST'
    display_name = 'Ghost'
    personality = 'Conflict and instability. Works in shadows. Reads GDELT like others read Twitter. Never loud, always right.'
    domain_context = (
        'Conflict, instability and security intelligence for frontier markets. '
        'Watch: GDELT conflict index elevations in EM regions, ACLED conflict data, '
        'armed group activity near mining/energy/port infrastructure, '
        'protest events, coup indicators, security force movements. '
        'Flag: sustained GDELT elevation (historically precedes escalation), '
        'infrastructure attacks, shipping route security deterioration, '
        'evacuation advisories from embassies. '
        'Frame: physical security risk to assets, operations, and supply chains.'
    )
    interval_minutes = 40

    def fetch_data(self) -> list:
        items = []
        try:
            resp = httpx.get(
                'https://api.gdeltproject.org/api/v2/doc/doc'
                '?query=conflict+attack+africa&mode=artlist&maxrecords=10&format=json',
                timeout=12, headers={'User-Agent': 'AlphaOps/1.0'}
            )
            if resp.status_code == 200:
                for article in resp.json().get('articles', [])[:6]:
                    items.append({
                        'source': 'gdelt',
                        'type': 'conflict_signal',
                        'title': article.get('title', ''),
                        'url': article.get('url', ''),
                        'tone': article.get('tone', 0),
                        'domain': article.get('domain', ''),
                    })
        except Exception as e:
            logger.warning(f"[GHOST] GDELT conflict: {e}")

        try:
            resp = httpx.get(
                'https://api.acleddata.com/acled/read?key=ACLED_API_KEY&email=ops@alphaops.io'
                '&country=Nigeria|Ethiopia|Kenya|Somalia|Sudan|Mali|Burkina+Faso'
                '&limit=10&fields=event_date|event_type|country|location|fatalities|notes',
                timeout=12, headers={'User-Agent': 'AlphaOps/1.0'}
            )
            if resp.status_code == 200:
                for event in resp.json().get('data', [])[:6]:
                    items.append({
                        'source': 'acled',
                        'type': 'conflict_event',
                        'title': f"{event.get('event_type', 'Event')} — {event.get('location', '')}, {event.get('country', '')}",
                        'fatalities': event.get('fatalities', 0),
                        'event_date': event.get('event_date', ''),
                        'notes': event.get('notes', '')[:200],
                        'url': 'https://acleddata.com',
                    })
        except Exception as e:
            logger.debug(f"[GHOST] ACLED: {e}")

        feeds = [
            ('https://rss.reliefweb.int/report/world', 'reliefweb'),
            ('https://www.crisisgroup.org/rss.xml', 'crisis_group'),
        ]
        for url, source in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:4]:
                    items.append({
                        'source': source,
                        'type': 'conflict_report',
                        'title': entry.get('title', ''),
                        'summary': entry.get('summary', '')[:300],
                        'url': entry.get('link', ''),
                    })
            except Exception as e:
                logger.debug(f"[GHOST] Feed {source}: {e}")

        return items
