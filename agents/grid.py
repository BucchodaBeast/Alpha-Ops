"""
agents/grid.py — THE GRID
Layer 2: Entity Extraction + Signal Corroboration

Runs after signals arrive. Extracts structured entities from every post,
then cross-corroborates signals across analysts to build entity clusters.

Entity schema: country, region, sector, asset_class, commodity, company,
               event_type, severity
"""

import json
import logging
import time
import hashlib
from datetime import datetime, timezone, timedelta
from database import Database

logger = logging.getLogger(__name__)

try:
    from agents.base import _call_groq
except ImportError:
    def _call_groq(*args, **kwargs):
        return None

# ── Entity extraction prompt ──────────────────────────────────────────────────
GRID_EXTRACT_PROMPT = """\
You are a structured entity extraction engine for an emerging markets
intelligence platform.

Extract all structured entities from the intelligence signal provided.
Be specific and conservative — only extract what is explicitly present or
strongly implied. Do not invent entities.

Return ONLY valid JSON:
{
  "countries": ["ISO country names only, e.g. Nigeria, Bangladesh, Vietnam"],
  "regions": ["sub-regions or economic zones, e.g. Horn of Africa, Mekong Delta, Gulf of Guinea"],
  "sectors": ["e.g. Garment Manufacturing, Oil & Gas, Agricultural Commodities, Maritime Logistics"],
  "asset_classes": ["e.g. EM Sovereign Bonds, Frontier Equities, Crude Oil Futures, Cotton Futures"],
  "commodities": ["e.g. Crude Oil, Cotton, Palm Oil, Copper, Natural Gas, Wheat"],
  "companies": ["only if specifically named"],
  "event_types": ["e.g. Supply Chain Disruption, Political Instability, Disease Outbreak, Port Congestion, Currency Crisis, Conflict Escalation, Regulatory Change"],
  "severity": "LOW | MEDIUM | HIGH | CRITICAL",
  "em_relevance": "direct | indirect | background"
}"""

# ── Corroboration scoring ─────────────────────────────────────────────────────
ENTITY_WEIGHT = {
    'countries': 3.0,
    'regions': 2.0,
    'sectors': 2.5,
    'commodities': 2.0,
    'event_types': 1.5,
    'asset_classes': 1.0,
    'companies': 3.0,
}

SEVERITY_SCORE = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'CRITICAL': 4}


def _parse_arr(v):
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v]
    if isinstance(v, str):
        try:
            r = json.loads(v)
            return [str(x).strip().lower() for x in r] if isinstance(r, list) else []
        except Exception:
            return []
    return []


class GridProcessor:
    name = 'GRID'
    display_name = 'The Grid'
    interval_minutes = 15

    def __init__(self):
        self.db = Database()

    # ── Entity extraction ─────────────────────────────────────────────────────

    def extract_entities(self, post: dict) -> dict | None:
        """Extract structured entities from a single post via LLM."""
        body = post.get('body', '')
        facts = _parse_arr(post.get('facts', []))
        tags = _parse_arr(post.get('tags', []))

        payload = f"Signal body: {body}\nFacts: {'; '.join(facts[:5])}\nTags: {', '.join(tags)}"

        parsed = _call_groq(
            agent_name='GRID',
            domain_context='Emerging market entity extraction',
            data_payload=payload,
            max_tokens=400,
        )

        if not parsed:
            # Fallback: build minimal entities from tags
            return {
                'countries': [],
                'regions': [],
                'sectors': [],
                'asset_classes': [],
                'commodities': [],
                'companies': [],
                'event_types': tags[:3],
                'severity': 'LOW',
                'em_relevance': 'background',
            }

        return {
            'countries': parsed.get('countries', []),
            'regions': parsed.get('regions', []),
            'sectors': parsed.get('sectors', []),
            'asset_classes': parsed.get('asset_classes', []),
            'commodities': parsed.get('commodities', []),
            'companies': parsed.get('companies', []),
            'event_types': parsed.get('event_types', []),
            'severity': parsed.get('severity', 'LOW'),
            'em_relevance': parsed.get('em_relevance', 'background'),
        }

    # ── Corroboration ─────────────────────────────────────────────────────────

    def build_clusters(self, enriched_posts: list) -> list:
        """
        Cross-corroborate enriched posts. Build entity clusters where
        multiple independent analysts share the same entity values.
        Returns clusters sorted by corroboration score descending.
        """
        # Index: entity_type → entity_value → list of posts
        entity_index: dict[str, dict[str, list]] = {k: {} for k in ENTITY_WEIGHT}

        for ep in enriched_posts:
            entities = ep.get('entities', {})
            analyst = ep.get('analyst', '')
            post_id = ep.get('id', '')
            confidence = float(ep.get('confidence', 0.3))
            severity = entities.get('severity', 'LOW')

            for etype in ENTITY_WEIGHT:
                for val in entities.get(etype, []):
                    val = val.strip().lower()
                    if not val or len(val) < 2:
                        continue
                    if val not in entity_index[etype]:
                        entity_index[etype][val] = []
                    entity_index[etype][val].append({
                        'analyst': analyst,
                        'post_id': post_id,
                        'confidence': confidence,
                        'severity': severity,
                        'body': ep.get('body', '')[:200],
                    })

        clusters = []
        seen_cluster_keys = set()

        for etype, entities in entity_index.items():
            weight = ENTITY_WEIGHT[etype]
            for val, mentions in entities.items():
                # Need 2+ independent analysts
                analysts_set = set(m['analyst'] for m in mentions)
                if len(analysts_set) < 2:
                    continue

                cluster_key = f"{etype}:{val}"
                if cluster_key in seen_cluster_keys:
                    continue
                seen_cluster_keys.add(cluster_key)

                avg_conf = sum(m['confidence'] for m in mentions) / len(mentions)
                max_severity = max(
                    (SEVERITY_SCORE.get(m['severity'], 1) for m in mentions),
                    default=1
                )
                corroboration_score = round(
                    len(analysts_set) * weight * avg_conf * (max_severity / 2),
                    3
                )

                clusters.append({
                    'entity_type': etype,
                    'entity_value': val,
                    'analysts': list(analysts_set),
                    'analyst_count': len(analysts_set),
                    'mention_count': len(mentions),
                    'corroboration_score': corroboration_score,
                    'avg_confidence': round(avg_conf, 3),
                    'max_severity': list(SEVERITY_SCORE.keys())[max_severity - 1],
                    'post_ids': list({m['post_id'] for m in mentions}),
                    'sample_signals': [m['body'] for m in mentions[:3]],
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                })

        clusters.sort(key=lambda x: x['corroboration_score'], reverse=True)
        return clusters[:50]  # Top 50 clusters

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self) -> dict:
        logger.info("[GRID] Starting entity extraction and corroboration...")
        start = time.time()

        posts = self.db.get_recent_posts(hours=8)
        if not posts:
            logger.info("[GRID] No recent posts to process")
            return {'enriched': 0, 'clusters': 0}

        enriched_posts = []
        processed = 0

        for post in posts[:40]:  # Cap at 40 to preserve Groq budget
            entities = self.extract_entities(post)
            if entities:
                post['entities'] = entities
                enriched_posts.append(post)
                processed += 1
            time.sleep(0.3)  # Rate limit breathing room

        clusters = self.build_clusters(enriched_posts)

        # Store clusters in DB
        self.db.store_grid_clusters(clusters)

        duration = time.time() - start
        self.db.log_agent_run('GRID', 'success', processed, len(clusters))
        logger.info(f"[GRID] {processed} posts enriched, {len(clusters)} clusters in {duration:.1f}s")

        return {'enriched': processed, 'clusters': len(clusters)}
