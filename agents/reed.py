"""
REED — Research & Technology Intelligence (was SYNTHESIS)
Academic who got tired of academia. Connects dots that aren't supposed to connect.
Focused on technology and research with EM investment implications.
"""
import logging
import feedparser
import httpx
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class ReedAgent(BaseAgent):
    name = 'REED'
    display_name = 'Reed'
    personality = 'Academic who got tired of academia. Reads 400 papers a week. Connects dots that aren\'t supposed to connect.'
    domain_context = (
        'Technology and research intelligence with emerging market investment implications. '
        'Watch: arXiv papers on AI/fintech/agritech, academic research on EM economies, '
        'technology adoption curves in frontier markets, patent filings in EM sectors. '
        'Flag: research that signals disruption to EM industries, '
        'technology leapfrogging opportunities (mobile money, solar, biotech). '
        'Frame: which technologies are about to change the economics of a frontier market.'
    )
    interval_minutes = 90

    def fetch_data(self) -> list:
        items = []
        arxiv_queries = [
            ('fintech emerging markets', 'FinTech/EM Finance'),
            ('agricultural technology africa', 'AgriTech Africa'),
            ('mobile money financial inclusion', 'Mobile Finance'),
            ('supply chain disruption prediction', 'Supply Chain'),
        ]
        for query, label in arxiv_queries:
            try:
                resp = httpx.get(
                    'http://export.arxiv.org/api/query',
                    params={
                        'search_query': f'all:{query}',
                        'start': 0, 'max_results': 3,
                        'sortBy': 'submittedDate', 'sortOrder': 'descending'
                    },
                    timeout=15, headers={'User-Agent': 'AlphaOps/1.0'}
                )
                if resp.status_code == 200:
                    feed = feedparser.parse(resp.text)
                    for entry in feed.entries[:3]:
                        items.append({
                            'source': 'arxiv',
                            'label': label,
                            'type': 'research_paper',
                            'title': entry.get('title', '').replace('\n', ' '),
                            'summary': entry.get('summary', '')[:400],
                            'url': entry.get('link', ''),
                            'published': entry.get('published', ''),
                        })
            except Exception as e:
                logger.debug(f"[REED] arXiv query '{query}': {e}")

        try:
            feed = feedparser.parse('https://techcrunch.com/category/africa/feed/')
            for entry in feed.entries[:5]:
                items.append({
                    'source': 'techcrunch_africa',
                    'type': 'tech_news',
                    'title': entry.get('title', ''),
                    'summary': entry.get('summary', '')[:300],
                    'url': entry.get('link', ''),
                })
        except Exception as e:
            logger.debug(f"[REED] TechCrunch Africa: {e}")

        return items
