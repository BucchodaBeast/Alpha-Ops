"""
agents/base.py — Alpha Ops Base Agent
Shared infrastructure: Groq LLM caller, deduplication, run pipeline.
Focused on Emerging Markets + Frontier Capital intelligence.
"""

import os
import json
import hashlib
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

import httpx
from database import Database

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
GROQ_MODEL = 'llama-3.3-70b-versatile'

# Confidence ceiling per source count
SOURCE_CONFIDENCE_CAP = {0: 0.20, 1: 0.45, 2: 0.65, 3: 0.80, 4: 0.90}

SYSTEM_PROMPT = """\
You are a structured intelligence analysis engine focused on Emerging Markets
and Frontier Capital. Your domain: Sub-Saharan Africa, Southeast Asia, South Asia,
MENA, and Frontier investment markets.

Your role: extract verifiable signal from raw data and produce machine-readable
intelligence with explicit uncertainty markers.

HARD RULES — violating these invalidates the entire output:
1. NEVER invent facts, causality, or sources not present in the input data
2. NEVER state inferences as facts — label them explicitly as inferences
3. NEVER set confidence above 0.7 without 3+ independent corroborating sources
4. ALWAYS quantify what is unknown in uncertainty_notes
5. If evidence is weak or ambiguous, say so — low confidence is correct output
6. source_urls MUST be URLs actually present in the input data, not invented
7. Frame analysis for: frontier fund managers, supply chain directors, commodity traders

Output ONLY valid JSON matching this schema exactly:
{
  "type": "signal | alert | breakthrough | opportunity",
  "body": "2-3 sentence intelligence summary. State what was observed, not interpretation.",
  "facts": ["direct observations from data — no interpretation"],
  "inferences": ["reasoned conclusions, each prefixed with 'Inference:'"],
  "confidence": 0.0,
  "source_count": 0,
  "uncertainty_notes": "explicit statement of what is unknown or unverified",
  "source_urls": ["only URLs that appeared in the input data"],
  "tags": ["3-6 topic tags, lowercase, no spaces"]
}"""


def _call_groq(agent_name: str, domain_context: str, data_payload: str,
               max_tokens: int = 700) -> Optional[dict]:
    if not GROQ_API_KEY:
        return None

    user_prompt = (
        f"Analyst domain: {domain_context}\n\n"
        f"Raw intelligence data:\n{data_payload}\n\n"
        "Analyze and return structured intelligence JSON. "
        "Only report what the data actually shows."
    )

    for attempt in range(3):
        try:
            resp = httpx.post(
                GROQ_URL,
                headers={
                    'Authorization': f'Bearer {GROQ_API_KEY}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': GROQ_MODEL,
                    'messages': [
                        {'role': 'system', 'content': SYSTEM_PROMPT},
                        {'role': 'user', 'content': user_prompt},
                    ],
                    'temperature': 0.15,
                    'max_tokens': max_tokens,
                    'response_format': {'type': 'json_object'},
                },
                timeout=30,
            )

            if resp.status_code == 429:
                wait = 12 * (attempt + 1)
                logger.warning(f"[{agent_name}] Groq rate limit — waiting {wait}s")
                time.sleep(wait)
                continue

            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                if content.startswith('```'):
                    content = content.split('```')[1]
                    if content.startswith('json'):
                        content = content[4:]
                    content = content.strip()
                return json.loads(content)

            logger.error(f"[{agent_name}] Groq HTTP {resp.status_code}")
            return None

        except json.JSONDecodeError as e:
            logger.error(f"[{agent_name}] LLM returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"[{agent_name}] Groq call failed (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

    return None


def _clamp_confidence(confidence: float, source_count: int) -> float:
    confidence = max(0.0, min(1.0, float(confidence)))
    cap = SOURCE_CONFIDENCE_CAP.get(min(source_count, 4), SOURCE_CONFIDENCE_CAP[4])
    return min(confidence, cap)


def _stable_hash(item: dict) -> str:
    title = (item.get('title') or item.get('subject') or '').lower().strip()[:200]
    url = (item.get('url') or item.get('link') or '').strip()
    source = (item.get('source') or '').lower().strip()
    if not url:
        value = str(item.get('value') or item.get('price') or item.get('ticker') or '')
        content = f"{source}|{title}|{value}"
    else:
        content = f"{title}|{url}"
    return hashlib.sha256(content.encode()).hexdigest()[:20]


class BaseAgent(ABC):
    name = 'BaseAgent'
    display_name = 'Base'
    personality = 'Neutral intelligence analyst.'
    domain_context = 'General emerging market intelligence'
    interval_minutes = 60

    def __init__(self):
        self.db = Database()

    @abstractmethod
    def fetch_data(self) -> list:
        pass

    def deduplicate(self, items: list) -> list:
        new_items = []
        for item in items:
            h = _stable_hash(item)
            item['_hash'] = h
            if not self.db.check_seen(self.name, h):
                new_items.append(item)
        return new_items

    def think(self, items: list) -> list:
        if not items:
            return []
        posts = []
        for item in items[:5]:
            data_payload = {k: v for k, v in item.items()
                            if not k.startswith('_') and k != 'timestamp'}
            data_str = json.dumps(data_payload, default=str)

            if not GROQ_API_KEY:
                title = item.get('title') or item.get('subject') or 'Signal detected'
                source = item.get('source', 'unknown')
                posts.append({
                    'analyst': self.name,
                    'type': 'signal',
                    'body': f"[{source.upper()}] {title[:250]}",
                    'facts': [f"Source: {source}", f"Data: {data_str[:300]}"],
                    'inferences': [],
                    'tags': [self.name.lower(), source.lower()],
                    'confidence': 0.3,
                    'source_count': 1,
                    'uncertainty_notes': 'No LLM analysis — raw data summary only.',
                    'tier': 'free',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'source_urls': [item.get('url', '')] if item.get('url') else [],
                })
                continue

            parsed = _call_groq(
                agent_name=self.name,
                domain_context=self.domain_context,
                data_payload=data_str,
            )

            if not parsed:
                logger.warning(f"[{self.name}] LLM returned nothing for item")
                continue

            source_count = int(parsed.get('source_count', 1))
            raw_conf = float(parsed.get('confidence', 0.3))
            clamped = _clamp_confidence(raw_conf, source_count)

            llm_urls = parsed.get('source_urls', [])
            actual_url = item.get('url') or item.get('link') or ''
            validated_urls = []
            if actual_url:
                validated_urls.append(actual_url)
            for u in llm_urls:
                if isinstance(u, str) and u.startswith('http') and u not in validated_urls:
                    validated_urls.append(u)

            body = parsed.get('body', '').strip()
            facts = parsed.get('facts', [])
            if not body and not facts:
                continue

            posts.append({
                'analyst': self.name,
                'type': parsed.get('type', 'signal'),
                'body': body[:500],
                'facts': facts[:10],
                'inferences': parsed.get('inferences', [])[:5],
                'tags': parsed.get('tags', [self.name.lower()])[:8],
                'confidence': clamped,
                'source_count': source_count,
                'uncertainty_notes': parsed.get('uncertainty_notes', ''),
                'tier': 'free',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'source_urls': validated_urls[:5],
            })

        return posts

    def save(self, posts: list) -> int:
        saved = 0
        for post in posts:
            if self.db.insert_post(post):
                saved += 1
        return saved

    def _mark_items_seen(self, items: list):
        for item in items:
            h = item.get('_hash')
            if h:
                self.db.mark_seen(self.name, h)

    def run(self) -> int:
        logger.info(f"[{self.name}] Starting run")
        start = time.time()
        try:
            items = self.fetch_data()
            logger.info(f"[{self.name}] Fetched {len(items)} items")

            new_items = self.deduplicate(items)
            logger.info(f"[{self.name}] {len(new_items)} new after dedup")

            if not new_items:
                self.db.log_agent_run(self.name, 'skipped', len(items), 0)
                return 0

            posts = self.think(new_items)
            saved = self.save(posts)
            self._mark_items_seen(new_items)

            duration = time.time() - start
            self.db.log_agent_run(self.name, 'success', len(items), saved)
            logger.info(f"[{self.name}] Saved {saved} posts in {duration:.1f}s")
            return saved

        except Exception as e:
            logger.error(f"[{self.name}] Run failed: {e}", exc_info=True)
            self.db.log_agent_run(self.name, 'error', error=str(e))
            return 0
