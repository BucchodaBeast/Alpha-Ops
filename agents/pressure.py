"""
agents/pressure.py — PRESSURE MAP
Layer 3: Magnitude Scoring + Regional Heat Engine

Consumes Grid clusters. Scores regions and sectors by:
- Signal accumulation velocity (how fast signals are building)
- Domain diversity (how many independent domains are pointing at same target)
- Severity escalation (are signals getting more severe over time)
- Cross-entity correlation (same country + sector + event_type = compound risk)

Produces a pressure map: ranked list of country/sector pressure zones.
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from database import Database

logger = logging.getLogger(__name__)

# How much each analyst domain contributes to pressure diversity
DOMAIN_DIVERSITY_WEIGHT = {
    'STONE':  'financial',
    'VOSS':   'financial',
    'MARA':   'health',
    'REED':   'technology',
    'ATLAS':  'geopolitical',
    'WATT':   'energy',
    'TIDE':   'maritime',
    'ECHO':   'social',
    'LEX':    'regulatory',
    'FINN':   'investment',
    'CARGO':  'supply_chain',
    'TERRA':  'climate',
    'DELPHI': 'probabilistic',
    'GHOST':  'conflict',
}

SEVERITY_MULTIPLIER = {'LOW': 1.0, 'MEDIUM': 1.5, 'HIGH': 2.5, 'CRITICAL': 4.0}

# Compound risk: when these event_types co-occur, multiply pressure
COMPOUND_RISK_PAIRS = [
    ('conflict escalation', 'supply chain disruption'),
    ('political instability', 'currency crisis'),
    ('disease outbreak', 'supply chain disruption'),
    ('port congestion', 'political instability'),
    ('climate event', 'supply chain disruption'),
    ('regulatory change', 'currency crisis'),
    ('conflict escalation', 'port congestion'),
]


class PressureProcessor:
    name = 'PRESSURE'
    display_name = 'Pressure Map'
    interval_minutes = 20

    def __init__(self):
        self.db = Database()

    def _velocity_score(self, signal_timestamps: list) -> float:
        """
        Score how fast signals are accumulating.
        More signals in shorter window = higher velocity.
        """
        if len(signal_timestamps) < 2:
            return 1.0
        now = datetime.now(timezone.utc)
        recent_1h = sum(
            1 for ts in signal_timestamps
            if (now - datetime.fromisoformat(ts.replace('Z', '+00:00'))).seconds < 3600
        )
        recent_6h = len(signal_timestamps)
        velocity = (recent_1h * 3.0 + recent_6h * 1.0) / max(recent_6h, 1)
        return round(min(velocity, 5.0), 3)

    def _domain_diversity_score(self, analysts: list) -> float:
        """
        Score how many independent domains are pointing at this entity.
        5 domains from same analyst = low diversity.
        5 signals from 5 different domains = high diversity.
        """
        domains = set(DOMAIN_DIVERSITY_WEIGHT.get(a, 'other') for a in analysts)
        return round(min(len(domains) / 7.0, 1.0), 3)  # Max 7 distinct domains

    def _compound_risk_multiplier(self, event_types: list) -> float:
        """Check for dangerous event type co-occurrences."""
        et_lower = [e.lower() for e in event_types]
        multiplier = 1.0
        for a, b in COMPOUND_RISK_PAIRS:
            a_present = any(a in et for et in et_lower)
            b_present = any(b in et for et in et_lower)
            if a_present and b_present:
                multiplier *= 1.4
        return round(min(multiplier, 3.0), 3)

    def compute_pressure_zones(self, clusters: list, recent_posts: list) -> list:
        """
        Build pressure zones from Grid clusters.
        A pressure zone is a country or region with a computed pressure score.
        """
        # Group clusters by country/region
        country_data: dict[str, dict] = defaultdict(lambda: {
            'analysts': set(),
            'domains': set(),
            'event_types': set(),
            'sectors': set(),
            'asset_classes': set(),
            'severities': [],
            'post_ids': set(),
            'signal_timestamps': [],
            'corroboration_scores': [],
            'cluster_count': 0,
        })

        for cluster in clusters:
            etype = cluster.get('entity_type', '')
            val = cluster.get('entity_value', '')
            analysts = cluster.get('analysts', [])
            severity = cluster.get('max_severity', 'LOW')
            post_ids = cluster.get('post_ids', [])
            score = cluster.get('corroboration_score', 0)

            # Determine target geography
            if etype == 'countries':
                targets = [val]
            elif etype == 'regions':
                targets = [val]
            else:
                # Non-geographic cluster — attach to countries mentioned nearby
                # Find posts in this cluster and check their country entities
                targets = []
                for pid in post_ids[:3]:
                    post = next((p for p in recent_posts if p.get('id') == pid), None)
                    if post:
                        entities = post.get('entities', {})
                        targets.extend(entities.get('countries', []))
                        targets.extend(entities.get('regions', []))
                if not targets:
                    continue

            for target in set(targets):
                d = country_data[target]
                d['analysts'].update(analysts)
                d['domains'].update(
                    DOMAIN_DIVERSITY_WEIGHT.get(a, 'other') for a in analysts
                )
                d['severities'].append(severity)
                d['post_ids'].update(post_ids)
                d['corroboration_scores'].append(score)
                d['cluster_count'] += 1

                if etype == 'event_types':
                    d['event_types'].add(val)
                elif etype == 'sectors':
                    d['sectors'].add(val)
                elif etype == 'asset_classes':
                    d['asset_classes'].add(val)

        # Attach timestamps from posts
        for post in recent_posts:
            entities = post.get('entities', {})
            ts = post.get('timestamp', '')
            if not ts:
                continue
            targets = entities.get('countries', []) + entities.get('regions', [])
            for t in targets:
                if t in country_data:
                    country_data[t]['signal_timestamps'].append(ts)

        # Score each zone
        zones = []
        for geography, data in country_data.items():
            if data['cluster_count'] < 2:
                continue

            analyst_list = list(data['analysts'])
            domain_div = self._domain_diversity_score(analyst_list)
            velocity = self._velocity_score(data['signal_timestamps'])
            compound = self._compound_risk_multiplier(list(data['event_types']))

            max_sev = max(
                (SEVERITY_MULTIPLIER.get(s, 1.0) for s in data['severities']),
                default=1.0
            )
            avg_corr = (
                sum(data['corroboration_scores']) / len(data['corroboration_scores'])
                if data['corroboration_scores'] else 0
            )

            pressure_score = round(
                avg_corr * domain_div * velocity * compound * (max_sev / 2),
                3
            )

            # Heat level
            if pressure_score >= 8.0:
                heat = 'CRITICAL'
            elif pressure_score >= 4.0:
                heat = 'HIGH'
            elif pressure_score >= 1.5:
                heat = 'ELEVATED'
            else:
                heat = 'MONITORING'

            zones.append({
                'geography': geography,
                'pressure_score': pressure_score,
                'heat_level': heat,
                'analyst_count': len(data['analysts']),
                'analysts': analyst_list,
                'domain_count': len(data['domains']),
                'domains': list(data['domains']),
                'domain_diversity': domain_div,
                'velocity_score': velocity,
                'compound_multiplier': compound,
                'cluster_count': data['cluster_count'],
                'signal_count': len(data['post_ids']),
                'event_types': list(data['event_types'])[:6],
                'sectors': list(data['sectors'])[:6],
                'asset_classes': list(data['asset_classes'])[:4],
                'max_severity': max(data['severities'], key=lambda s: SEVERITY_MULTIPLIER.get(s, 1), default='LOW'),
                'post_ids': list(data['post_ids'])[:20],
                'timestamp': datetime.now(timezone.utc).isoformat(),
            })

        zones.sort(key=lambda z: z['pressure_score'], reverse=True)
        return zones[:30]  # Top 30 pressure zones

    def run(self) -> dict:
        logger.info("[PRESSURE] Computing pressure map...")
        start = time.time()

        clusters = self.db.get_grid_clusters(limit=200)
        recent_posts = self.db.get_recent_posts(hours=8)

        if not clusters:
            logger.info("[PRESSURE] No grid clusters yet")
            return {'zones': 0}

        zones = self.compute_pressure_zones(clusters, recent_posts)
        self.db.store_pressure_zones(zones)

        duration = time.time() - start
        self.db.log_agent_run('PRESSURE', 'success', len(clusters), len(zones))
        logger.info(f"[PRESSURE] {len(zones)} pressure zones computed in {duration:.1f}s")

        return {'zones': len(zones)}
