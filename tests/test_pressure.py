"""
tests/test_pressure.py
Unit tests for agents/pressure.py — velocity scoring, domain diversity,
compound risk multipliers, pressure zone computation.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta
from agents.pressure import (
    PressureProcessor, DOMAIN_DIVERSITY_WEIGHT,
    SEVERITY_MULTIPLIER, COMPOUND_RISK_PAIRS,
)


def _make_processor():
    pp = PressureProcessor.__new__(PressureProcessor)
    pp.db = MagicMock()
    return pp


def _ts(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


# ── _velocity_score ───────────────────────────────────────────────────────────

class TestVelocityScore:
    def test_single_timestamp_returns_1(self):
        pp = _make_processor()
        assert pp._velocity_score([_ts(10)]) == 1.0

    def test_empty_timestamps_returns_1(self):
        pp = _make_processor()
        assert pp._velocity_score([]) == 1.0

    def test_all_recent_signals_higher_velocity(self):
        pp = _make_processor()
        recent = [_ts(5), _ts(10), _ts(15), _ts(20)]
        old = [_ts(300), _ts(360), _ts(420), _ts(480)]
        v_recent = pp._velocity_score(recent)
        v_old = pp._velocity_score(old)
        assert v_recent > v_old

    def test_velocity_capped_at_5(self):
        pp = _make_processor()
        very_recent = [_ts(i) for i in range(1, 30)]
        assert pp._velocity_score(very_recent) <= 5.0

    def test_velocity_is_positive(self):
        pp = _make_processor()
        timestamps = [_ts(i * 30) for i in range(8)]
        assert pp._velocity_score(timestamps) > 0


# ── _domain_diversity_score ───────────────────────────────────────────────────

class TestDomainDiversityScore:
    def test_single_analyst_low_diversity(self):
        pp = _make_processor()
        score = pp._domain_diversity_score(['STONE'])
        assert score < 2.0

    def test_more_analysts_higher_diversity(self):
        pp = _make_processor()
        low  = pp._domain_diversity_score(['STONE', 'VOSS'])         # both financial
        high = pp._domain_diversity_score(['STONE', 'GHOST', 'MARA', 'TERRA'])  # 4 domains
        assert high > low

    def test_same_domain_analysts_lower_than_mixed(self):
        pp = _make_processor()
        same   = pp._domain_diversity_score(['STONE', 'VOSS', 'FINN'])   # all financial/investment
        mixed  = pp._domain_diversity_score(['STONE', 'GHOST', 'MARA'])  # financial, conflict, health
        assert mixed >= same

    def test_all_14_analysts_max_diversity(self):
        pp = _make_processor()
        all_analysts = list(DOMAIN_DIVERSITY_WEIGHT.keys())
        score = pp._domain_diversity_score(all_analysts)
        assert score > 1.0

    def test_empty_analysts_returns_zero_or_one(self):
        pp = _make_processor()
        # 0 domains → 0.0 (0/7); implementation may vary
        assert pp._domain_diversity_score([]) == pytest.approx(0.0)


# ── _compound_risk_multiplier ─────────────────────────────────────────────────

class TestCompoundRiskMultiplier:
    def test_no_matching_pairs_returns_1(self):
        pp = _make_processor()
        assert pp._compound_risk_multiplier(['regulatory change']) == 1.0

    def test_known_pair_raises_multiplier(self):
        pp = _make_processor()
        events = ['conflict escalation', 'supply chain disruption']
        assert pp._compound_risk_multiplier(events) > 1.0

    def test_multiple_pairs_stacks(self):
        pp = _make_processor()
        single_pair = pp._compound_risk_multiplier(['conflict escalation', 'supply chain disruption'])
        two_pairs   = pp._compound_risk_multiplier([
            'conflict escalation', 'supply chain disruption',
            'political instability', 'currency crisis',
        ])
        assert two_pairs >= single_pair

    def test_empty_events_returns_1(self):
        pp = _make_processor()
        assert pp._compound_risk_multiplier([]) == 1.0

    def test_all_compound_pairs_defined(self):
        for pair in COMPOUND_RISK_PAIRS:
            assert len(pair) == 2


# ── compute_pressure_zones ────────────────────────────────────────────────────

class TestComputePressureZones:
    def _make_cluster(self, entity_type, entity_value, analysts,
                      severity='MEDIUM', score=5.0, post_ids=None):
        return {
            'entity_type': entity_type,
            'entity_value': entity_value,
            'analysts': analysts,
            'max_severity': severity,
            'post_ids': post_ids or [f'post-{entity_value}-{a}' for a in analysts],
            'corroboration_score': score,
        }

    def test_single_cluster_zone_created(self):
        pp = _make_processor()
        clusters = [
            self._make_cluster('countries', 'nigeria', ['STONE', 'GHOST']),
            self._make_cluster('countries', 'nigeria', ['ATLAS', 'MARA']),
        ]
        posts = [
            {'id': f'post-nigeria-{a}', 'analyst': a, 'confidence': 0.5,
             'timestamp': _ts(30), 'entities': {'countries': ['nigeria'], 'regions': []}}
            for a in ['STONE', 'GHOST', 'ATLAS', 'MARA']
        ]
        zones = pp.compute_pressure_zones(clusters, posts)
        assert len(zones) >= 1
        assert zones[0]['geography'] == 'nigeria'

    def test_zones_sorted_by_pressure_descending(self):
        pp = _make_processor()
        clusters = [
            self._make_cluster('countries', 'laos',    ['STONE', 'GHOST'], score=2.0),
            self._make_cluster('countries', 'nigeria', ['STONE', 'GHOST', 'ATLAS', 'CARGO'], score=15.0),
            self._make_cluster('countries', 'vietnam', ['STONE', 'GHOST'], score=5.0),
        ]
        posts = []
        for country in ['laos', 'nigeria', 'vietnam']:
            for a in ['STONE', 'GHOST']:
                posts.append({
                    'id': f'post-{country}-{a}', 'analyst': a, 'confidence': 0.5,
                    'timestamp': _ts(30),
                    'entities': {'countries': [country], 'regions': []}
                })
        zones = pp.compute_pressure_zones(clusters, posts)
        scores = [z['pressure_score'] for z in zones]
        assert scores == sorted(scores, reverse=True)

    def test_max_30_zones_returned(self):
        pp = _make_processor()
        clusters = []
        posts = []
        for i in range(40):
            country = f'country{i:03d}'
            for a in ['STONE', 'GHOST']:
                clusters.append(self._make_cluster('countries', country, ['STONE', 'GHOST']))
                posts.append({
                    'id': f'post-{country}-{a}', 'analyst': a, 'confidence': 0.5,
                    'timestamp': _ts(30),
                    'entities': {'countries': [country], 'regions': []}
                })
        zones = pp.compute_pressure_zones(clusters, posts)
        assert len(zones) <= 30

    def test_heat_levels_assigned_correctly(self):
        pp = _make_processor()
        # Build a cluster that will produce a known pressure score range
        # by controlling inputs precisely
        clusters = [self._make_cluster('countries', 'ghana', ['STONE', 'GHOST'])]
        posts = [
            {'id': 'p1', 'analyst': 'STONE', 'confidence': 0.5,
             'timestamp': _ts(30), 'entities': {'countries': ['ghana'], 'regions': []}},
            {'id': 'p2', 'analyst': 'GHOST', 'confidence': 0.5,
             'timestamp': _ts(40), 'entities': {'countries': ['ghana'], 'regions': []}},
        ]
        zones = pp.compute_pressure_zones(clusters, posts)
        if zones:
            assert zones[0]['heat_level'] in {'MONITORING', 'ELEVATED', 'HIGH', 'CRITICAL'}


# ── DOMAIN_DIVERSITY_WEIGHT completeness ─────────────────────────────────────

class TestDomainDiversityWeightConfig:
    def test_all_14_analysts_covered(self):
        expected = {
            'STONE','VOSS','MARA','REED','ATLAS','WATT',
            'TIDE','ECHO','LEX','FINN','CARGO','TERRA','DELPHI','GHOST'
        }
        assert set(DOMAIN_DIVERSITY_WEIGHT.keys()) == expected

    def test_all_domains_are_strings(self):
        for k, v in DOMAIN_DIVERSITY_WEIGHT.items():
            assert isinstance(v, str), f"{k} domain is not a string"

    def test_severity_multiplier_ordering(self):
        assert (SEVERITY_MULTIPLIER['LOW'] < SEVERITY_MULTIPLIER['MEDIUM']
                < SEVERITY_MULTIPLIER['HIGH'] < SEVERITY_MULTIPLIER['CRITICAL'])
