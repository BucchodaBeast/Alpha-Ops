"""
agents/desk.py — THE DESK
Layer 4: NEXUS Brief synthesis engine.

Consumes enriched data from all three prior layers:
- Layer 1 (Wire): raw analyst signals
- Layer 2 (Grid): entity clusters + corroboration scores
- Layer 3 (Pressure): regional pressure zones + magnitude scores

Produces NEXUS Briefs — finished professional intelligence products.
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

CONFIDENCE_TIERS = {
    (0.0,  0.40): 'EARLY WARNING',
    (0.40, 0.60): 'DEVELOPING',
    (0.60, 0.80): 'CONFIRMED',
    (0.80, 1.01): 'HIGH CONFIDENCE',
}

NEXUS_SYSTEM_PROMPT = """\
You are THE DESK — the senior intelligence synthesis unit of Alpha Ops,
an emerging markets and frontier capital intelligence platform.

You receive fully processed intelligence from four pipeline layers:
- Raw analyst signals (The Wire)
- Corroborated entity clusters (The Grid)
- Regional pressure scores (Pressure Map)
- Convergence candidates with analyst attribution

Your output is a NEXUS BRIEF — the finished product of the entire system.
It must read like something a senior analyst at a top-tier intelligence
firm spent three hours writing. It is read by frontier fund managers,
supply chain directors, and commodity traders making decisions worth millions.

ABSOLUTE RULES:
1. Every claim must be attributable to a named analyst or data layer
2. Be ruthlessly specific — name the country, city, port, company, commodity
3. Never use hedging clichés ("it remains to be seen", "could potentially")
4. The so_what must answer: what does this mean for money RIGHT NOW
5. Historical precedent must be real and named if cited — never invented
6. Confidence scores must reflect actual signal quality, not optimism
7. If the signal is weak, say so — a precise EARLY WARNING is more valuable than a false CONFIRMED

Return ONLY valid JSON with this exact schema:
{
  "title": "Specific, factual, under 90 chars. No vague abstractions. Name the geography and event.",
  "synthesis": "4-6 sentences. Which analysts flagged what, independently. What the Grid corroborated. What the Pressure Map shows building. Be specific about entities — name countries, ports, sectors.",
  "so_what": "3-4 sentences. Direct investment and operational implication. What a frontier fund manager, supply chain director, or commodity trader should think about RIGHT NOW. No hedging.",
  "who_affected": "Specific list: sectors, geographies, asset classes, companies if named. Format: primary exposure first, then secondary.",
  "timeline": "Specific window with reasoning. E.g. '14-21 days based on historical port disruption cycles' or '72-hour decision window before shipping alternatives close'.",
  "historical_precedent": "One named real-world comparable event if applicable. E.g. '2022 Sri Lanka crisis showed identical GHOST+CARGO+TERRA convergence pattern preceding supply chain collapse.' Leave empty string if no strong precedent.",
  "next_steps": "3 numbered concrete actions specific to this brief. Not generic. Tied to what was actually reported.",
  "what_to_watch": "3 numbered specific indicators with named data sources. E.g. '1. ILO field reports from Dhaka garment district. 2. Chittagong port booking cancellations via FreightWaves. 3. BDT/USD rate on Kraken.'",
  "confidence_tier": "EARLY WARNING | DEVELOPING | CONFIRMED | HIGH CONFIDENCE",
  "convergence_score": 0.0,
  "uncertainty_notes": "What the pipeline disagreed on or what remains unverified. Be honest."
}"""


def _deser(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v:
        try:
            r = json.loads(v)
            return r if isinstance(r, list) else []
        except Exception:
            return []
    return []


def _assign_tier(confidence: float) -> str:
    for (low, high), tier in CONFIDENCE_TIERS.items():
        if low <= confidence < high:
            return tier
    return 'EARLY WARNING'


class DeskAgent:
    name = 'DESK'
    display_name = 'The Desk'
    personality = (
        'Does not have a personality. Has a function. '
        'Takes everything the analysts produce and finds the shape underneath.'
    )
    interval_minutes = 25

    def __init__(self):
        self.db = Database()
        self._recently_briefed: dict[str, float] = {}
        self._briefed_ttl = 7200  # 2h debounce per topic

    def _was_briefed(self, key: str) -> bool:
        return (time.time() - self._recently_briefed.get(key, 0)) < self._briefed_ttl

    def _mark_briefed(self, key: str):
        self._recently_briefed[key] = time.time()
        cutoff = time.time() - self._briefed_ttl * 2
        self._recently_briefed = {k: v for k, v in self._recently_briefed.items() if v > cutoff}

    # ── Convergence detection from Wire tags ─────────────────────────────────

    def _detect_tag_convergence(self, posts: list) -> list:
        topic_clusters: dict[str, dict] = {}
        skip = {'signal','alert','free','premium','breakthrough','opportunity','background','direct','indirect'}

        for post in posts:
            analyst = post.get('analyst', '')
            body = post.get('body', '')
            confidence = float(post.get('confidence', 0.0))
            post_id = post.get('id', '')
            tags = _deser(post.get('tags', []))

            for tag in tags:
                if len(tag) <= 2 or tag.lower() in skip:
                    continue
                if tag not in topic_clusters:
                    topic_clusters[tag] = {
                        'analysts': {}, 'posts': [],
                        'post_ids': [], 'total_confidence': 0.0,
                    }
                c = topic_clusters[tag]
                if analyst not in c['analysts']:
                    c['analysts'][analyst] = []
                c['analysts'][analyst].append({'body': body, 'confidence': confidence})
                c['posts'].append(post)
                c['post_ids'].append(post_id)
                c['total_confidence'] += confidence

        candidates = []
        for topic, cluster in topic_clusters.items():
            agent_count = len(cluster['analysts'])
            if agent_count < 2:
                continue
            avg_conf = cluster['total_confidence'] / max(len(cluster['posts']), 1)
            if self._was_briefed(f"tag:{topic}"):
                continue
            if agent_count >= 3 and avg_conf >= 0.30:
                candidates.append({
                    'trigger': 'tag_convergence',
                    'key': f"tag:{topic}",
                    'topic': topic,
                    'analysts': list(cluster['analysts'].keys()),
                    'posts': cluster['posts'][:8],
                    'post_ids': cluster['post_ids'],
                    'avg_confidence': round(avg_conf, 3),
                    'analyst_count': agent_count,
                })
            elif agent_count >= 2 and avg_conf >= 0.42:
                candidates.append({
                    'trigger': 'tag_convergence',
                    'key': f"tag:{topic}",
                    'topic': topic,
                    'analysts': list(cluster['analysts'].keys()),
                    'posts': cluster['posts'][:8],
                    'post_ids': cluster['post_ids'],
                    'avg_confidence': round(avg_conf, 3),
                    'analyst_count': agent_count,
                })

        return candidates

    # ── Convergence detection from Pressure zones ─────────────────────────────

    def _detect_pressure_convergence(self, zones: list, posts: list) -> list:
        candidates = []
        for zone in zones:
            heat = zone.get('heat_level', 'MONITORING')
            if heat not in ('HIGH', 'CRITICAL'):
                continue
            geo = zone.get('geography', '')
            key = f"pressure:{geo}"
            if self._was_briefed(key):
                continue
            if zone.get('domain_count', 0) < 3:
                continue

            # Find posts related to this geography
            related_posts = []
            zone_post_ids = set(_deser(zone.get('post_ids', [])))
            for p in posts:
                if p.get('id') in zone_post_ids:
                    related_posts.append(p)

            if len(related_posts) < 3:
                continue

            analysts = list(set(p.get('analyst', '') for p in related_posts))
            avg_conf = sum(float(p.get('confidence', 0)) for p in related_posts) / len(related_posts)

            candidates.append({
                'trigger': 'pressure_zone',
                'key': key,
                'topic': geo,
                'geography': geo,
                'heat_level': heat,
                'pressure_score': zone.get('pressure_score', 0),
                'event_types': _deser(zone.get('event_types', [])),
                'sectors': _deser(zone.get('sectors', [])),
                'asset_classes': _deser(zone.get('asset_classes', [])),
                'domain_diversity': zone.get('domain_diversity', 0),
                'velocity_score': zone.get('velocity_score', 0),
                'compound_multiplier': zone.get('compound_multiplier', 1),
                'analysts': analysts,
                'posts': related_posts[:8],
                'post_ids': list(zone_post_ids),
                'avg_confidence': round(avg_conf, 3),
                'analyst_count': len(analysts),
            })

        return candidates

    # ── Grid cluster convergence ───────────────────────────────────────────────

    def _detect_grid_convergence(self, clusters: list, posts: list) -> list:
        candidates = []
        for cluster in clusters:
            if cluster.get('analyst_count', 0) < 3:
                continue
            if cluster.get('corroboration_score', 0) < 2.0:
                continue
            etype = cluster.get('entity_type', '')
            val = cluster.get('entity_value', '')
            key = f"grid:{etype}:{val}"
            if self._was_briefed(key):
                continue

            cluster_post_ids = set(_deser(cluster.get('post_ids', [])))
            related_posts = [p for p in posts if p.get('id') in cluster_post_ids]
            if len(related_posts) < 2:
                continue

            avg_conf = cluster.get('avg_confidence', 0.3)
            candidates.append({
                'trigger': 'grid_cluster',
                'key': key,
                'topic': f"{etype}: {val}",
                'entity_type': etype,
                'entity_value': val,
                'corroboration_score': cluster.get('corroboration_score', 0),
                'max_severity': cluster.get('max_severity', 'LOW'),
                'analysts': _deser(cluster.get('analysts', [])),
                'posts': related_posts[:8],
                'post_ids': list(cluster_post_ids),
                'avg_confidence': round(avg_conf, 3),
                'analyst_count': cluster.get('analyst_count', 0),
            })

        return candidates

    # ── NEXUS Brief synthesis ─────────────────────────────────────────────────

    def synthesize_nexus(self, candidate: dict,
                         grid_clusters: list,
                         pressure_zones: list) -> dict | None:

        topic = candidate.get('topic', '')
        analysts = candidate.get('analysts', [])
        posts = candidate.get('posts', [])
        avg_confidence = candidate.get('avg_confidence', 0.3)
        trigger = candidate.get('trigger', 'tag_convergence')

        # Ground confidence
        caps = {2: 0.52, 3: 0.68, 4: 0.80, 5: 0.88}
        base_conf = min(avg_confidence * 1.12, caps.get(min(len(analysts), 5), 0.88))

        # Boost for pressure zone triggers
        if trigger == 'pressure_zone':
            ps = candidate.get('pressure_score', 0)
            compound = candidate.get('compound_multiplier', 1)
            base_conf = min(base_conf * (1 + ps / 40) * (compound / 2), 0.92)

        # Boost for high grid corroboration
        if trigger == 'grid_cluster':
            cs = candidate.get('corroboration_score', 0)
            base_conf = min(base_conf * (1 + cs / 20), 0.90)

        grounded_conf = round(base_conf, 3)
        tier = _assign_tier(grounded_conf)

        brief_id = f"nexus_{hashlib.sha256(f'{topic}{time.time()}'.encode()).hexdigest()[:12]}"

        # Build rich data payload for THE DESK
        wire_reports = '\n'.join([
            f"  [{p.get('analyst','?')}] conf={p.get('confidence',0):.2f} | {p.get('body','')[:280]}"
            for p in posts
        ])

        # Attach relevant grid clusters
        relevant_clusters = [
            c for c in grid_clusters
            if any(a in _deser(c.get('analysts',[])) for a in analysts)
        ][:6]
        grid_summary = '\n'.join([
            f"  GRID CLUSTER: {c.get('entity_type')} = '{c.get('entity_value')}' | "
            f"analysts={','.join(_deser(c.get('analysts',[])))[:60]} | "
            f"corroboration={c.get('corroboration_score',0):.2f} | severity={c.get('max_severity','LOW')}"
            for c in relevant_clusters
        ]) or "  No Grid clusters attached."

        # Attach pressure zone if available
        geo = candidate.get('geography', topic)
        matching_zones = [z for z in pressure_zones if geo.lower() in z.get('geography','').lower()]
        pressure_summary = ''
        if matching_zones:
            z = matching_zones[0]
            pressure_summary = (
                f"\nPRESSURE MAP: {z.get('geography')} | "
                f"heat={z.get('heat_level')} | "
                f"score={z.get('pressure_score',0):.2f} | "
                f"domains={z.get('domain_count',0)} | "
                f"velocity={z.get('velocity_score',0):.2f} | "
                f"compound={z.get('compound_multiplier',1):.2f} | "
                f"event_types={','.join(_deser(z.get('event_types',[])))[:80]}"
            )

        data_payload = (
            f"CONVERGENCE TRIGGER: {trigger.upper()}\n"
            f"TOPIC/GEOGRAPHY: {topic}\n"
            f"ANALYSTS INVOLVED: {', '.join(analysts)}\n"
            f"AVERAGE PIPELINE CONFIDENCE: {avg_confidence:.2f}\n"
            f"ANALYST DOMAIN COUNT: {candidate.get('analyst_count',0)}\n\n"
            f"WIRE REPORTS (raw analyst signals):\n{wire_reports}\n\n"
            f"GRID CORROBORATION:\n{grid_summary}"
            f"{pressure_summary}"
        )

        # Fallback brief
        fallback = {
            'id': brief_id,
            'title': f"NEXUS: {topic.upper()[:80]}",
            'synthesis': (
                f"THE DESK detected convergence on '{topic}' across "
                f"{len(analysts)} analysts: {', '.join(analysts)}. "
                f"Trigger: {trigger}. Pipeline confidence: {avg_confidence:.0%}."
            ),
            'so_what': f"Multiple independent intelligence streams pointing at '{topic}'. Requires monitoring.",
            'who_affected': "Frontier market investors and supply chain operators with regional exposure.",
            'timeline': "Developing — assess over next 24-48 hours.",
            'historical_precedent': '',
            'next_steps': "1. Review regional exposure. 2. Monitor flagged indicators. 3. Check analyst feeds.",
            'what_to_watch': "1. Monitor analyst feed for escalation. 2. Track corroborating data sources.",
            'confidence_tier': tier,
            'analysts_involved': analysts,
            'contributing_post_ids': candidate.get('post_ids', []),
            'confidence': grounded_conf,
            'convergence_score': round(min(len(analysts) / 5.0, 1.0), 3),
            'brief_type': 'nexus',
            'trigger_type': trigger,
            'uncertainty_notes': 'Fallback brief — LLM synthesis unavailable.',
            'tier': 'free',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

        parsed = _call_groq(
            agent_name='DESK',
            domain_context='Emerging market NEXUS Brief synthesis for frontier fund managers and supply chain directors',
            data_payload=data_payload,
            max_tokens=1100,
        )

        if not parsed:
            logger.warning(f"[DESK] LLM failed for '{topic}' — using fallback")
            return fallback

        return {
            'id': brief_id,
            'title': (parsed.get('title') or fallback['title'])[:90],
            'synthesis': (parsed.get('synthesis') or fallback['synthesis'])[:900],
            'body': (parsed.get('synthesis') or fallback['synthesis'])[:900],  # DB compat
            'so_what': (parsed.get('so_what') or fallback['so_what'])[:500],
            'who_affected': (parsed.get('who_affected') or fallback['who_affected'])[:500],
            'timeline': (parsed.get('timeline') or fallback['timeline'])[:300],
            'historical_precedent': (parsed.get('historical_precedent') or '')[:400],
            'next_steps': (parsed.get('next_steps') or fallback['next_steps'])[:500],
            'what_to_watch': (parsed.get('what_to_watch') or fallback['what_to_watch'])[:500],
            'confidence_tier': parsed.get('confidence_tier', tier),
            'analysts_involved': analysts,
            'contributing_post_ids': candidate.get('post_ids', []),
            'confidence': grounded_conf,
            'convergence_score': round(float(parsed.get('convergence_score', 0.5)), 3),
            'brief_type': 'nexus',
            'trigger_type': trigger,
            'uncertainty_notes': (parsed.get('uncertainty_notes') or '')[:400],
            'tier': 'free',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self) -> int:
        logger.info("[DESK] Scanning all pipeline layers for NEXUS Brief candidates...")
        start = time.time()

        posts = self.db.get_recent_posts(hours=6)
        grid_clusters = self.db.get_grid_clusters(limit=100)
        pressure_zones = self.db.get_pressure_zones(limit=30)

        # Gather candidates from all three detection methods
        tag_candidates = self._detect_tag_convergence(posts)
        pressure_candidates = self._detect_pressure_convergence(pressure_zones, posts)
        grid_candidates = self._detect_grid_convergence(grid_clusters, posts)

        # Merge and deduplicate by topic
        all_candidates = []
        seen_topics: set[str] = set()

        # Priority: pressure > grid > tag
        for c in pressure_candidates + grid_candidates + tag_candidates:
            norm = c.get('topic', '').lower().strip()
            if norm not in seen_topics:
                seen_topics.add(norm)
                all_candidates.append(c)

        logger.info(
            f"[DESK] Candidates — pressure:{len(pressure_candidates)} "
            f"grid:{len(grid_candidates)} tag:{len(tag_candidates)} "
            f"merged:{len(all_candidates)}"
        )

        saved = 0
        for candidate in all_candidates[:5]:  # Max 5 NEXUS Briefs per run
            nexus = self.synthesize_nexus(candidate, grid_clusters, pressure_zones)
            if nexus:
                if self.db.insert_brief(nexus):
                    saved += 1
                    self._mark_briefed(candidate['key'])
                    logger.info(
                        f"[DESK] NEXUS BRIEF: '{nexus['title']}' "
                        f"tier={nexus['confidence_tier']} conf={nexus['confidence']:.2f} "
                        f"trigger={nexus.get('trigger_type','?')}"
                    )
                time.sleep(1)  # Rate limit buffer between briefs

        duration = time.time() - start
        self.db.log_agent_run('DESK', 'success', len(posts), saved)
        logger.info(f"[DESK] {saved} NEXUS Briefs written in {duration:.1f}s")
        return saved
