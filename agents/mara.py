"""
MARA — Health & Epidemic Intelligence (was VEXA)
Epidemiologist energy. Notices things nobody else notices until it's too late.
Focused on disease outbreaks that disrupt EM workforces and supply chains.
"""
import logging
import feedparser
import httpx
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class MaraAgent(BaseAgent):
    name = 'MARA'
    display_name = 'Mara'
    personality = 'Epidemiologist energy. Calm, clinical, slightly unsettling. Notices things nobody else notices until it\'s too late.'
    domain_context = (
        'Epidemic and health intelligence for emerging market workforce and supply chains. '
        'Watch: WHO outbreak alerts, CDC global health advisories, disease surveillance in '
        'Sub-Saharan Africa, Southeast Asia, South Asia. '
        'Flag: outbreaks affecting manufacturing zones, port cities, agricultural regions. '
        'Connect: disease outbreak → workforce disruption → supply chain delay → commodity price impact. '
        'Frame for: fund managers with EM exposure, supply chain directors, agricultural commodity traders.'
    )
    interval_minutes = 45

    def fetch_data(self) -> list:
        items = []
        try:
            feed = feedparser.parse('https://www.who.int/feeds/entity/csr/don/en/rss.xml')
            for entry in feed.entries[:8]:
                items.append({
                    'source': 'who_don',
                    'type': 'disease_outbreak',
                    'title': entry.get('title', ''),
                    'summary': entry.get('summary', '')[:500],
                    'url': entry.get('link', ''),
                    'published': entry.get('published', ''),
                })
        except Exception as e:
            logger.warning(f"[MARA] WHO DON feed error: {e}")

        try:
            feed = feedparser.parse('https://tools.cdc.gov/api/v2/resources/media/316422.rss')
            for entry in feed.entries[:5]:
                items.append({
                    'source': 'cdc_global',
                    'type': 'health_advisory',
                    'title': entry.get('title', ''),
                    'summary': entry.get('summary', '')[:300],
                    'url': entry.get('link', ''),
                })
        except Exception as e:
            logger.warning(f"[MARA] CDC feed error: {e}")

        try:
            resp = httpx.get(
                'https://www.promed.org/promed-rss',
                timeout=10, headers={'User-Agent': 'AlphaOps/1.0'}
            )
            if resp.status_code == 200:
                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:5]:
                    items.append({
                        'source': 'promed',
                        'type': 'disease_alert',
                        'title': entry.get('title', ''),
                        'url': entry.get('link', ''),
                    })
        except Exception as e:
            logger.debug(f"[MARA] ProMED error: {e}")

        return items
