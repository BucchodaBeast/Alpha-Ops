"""
tests/test_grid.py
Unit tests for agents/grid.py — entity clustering, corroboration scoring.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from agents.grid import GridProcessor, ENTITY_WEIGHT, SEVERITY_SCORE, _parse_arr


# ── _parse_arr ────────────────────────────────────────────────────────────────

class TestParseArr:
    def test_list_input_lowercased(self):
        assert _parse_arr(['Nigeria', 'KENYA']) == ['nigeria', 'kenya']

    def test_json_string_input(self):
        assert _parse_arr('["Vietnam", "Thailand"]') == ['vietnam', 'thailand']

    def test_empty_list(self):
        assert _parse_arr([]) == []

    def test_none_returns_empty(self):
        assert _parse_arr(None) == []

    def test_invalid_json_returns_empty(self):
        assert _parse_arr('not json at all') == []

    def test_whitespace_stripped(self):
        assert _parse_arr([' Nigeria ', 'Kenya ']) == ['nigeria', 'kenya']


# ── build_clusters ────────────────────────────────────────────────────────────

class TestBuildClusters:
    def _make_processor(self):
        gp = GridProcessor.__new__(GridProcessor)
        gp.db = MagicMock()
        return gp

    def _make_post(self, analyst, countries=None, sectors=None,
                   severity='MEDIUM', confidence=0.5, post_id=None):
        return {
            'id': post_id or f'post-{analyst}',
            'analyst': analyst,
            'body': f'Signal from {analyst}',
            'confidence': confidence,
            'entities': {
                'countries': countries or [],
                'regions': [],
                'sectors': sectors or [],
                'asset_classes': [],
                'commodities': [],
                'companies': [],
                'event_types': [],
                'severity': severity,
                'em_relevance': 'direct',
            }
        }

    def test_single_analyst_no_cluster(self):
        gp = self._make_processor()
        posts = [self._make_post('STONE', countries=['nigeria'])]
        clusters = gp.build_clusters(posts)
        assert clusters == []

    def test_two_analysts_same_country_creates_cluster(self):
        gp = self._make_processor()
        posts = [
            self._make_post('STONE', countries=['nigeria']),
            self._make_post('GHOST', countries=['nigeria']),
        ]
        clusters = gp.build_clusters(posts)
        assert len(clusters) == 1
        assert clusters[0]['entity_value'] == 'nigeria'
        assert clusters[0]['analyst_count'] == 2

    def test_cluster_includes_both_analysts(self):
        gp = self._make_processor()
        posts = [
            self._make_post('STONE', countries=['kenya']),
            self._make_post('ATLAS', countries=['kenya']),
        ]
        clusters = gp.build_clusters(posts)
        assert set(clusters[0]['analysts']) == {'STONE', 'ATLAS'}

    def test_three_analysts_higher_corroboration_than_two(self):
        gp = self._make_processor()
        two_posts = [
            self._make_post('STONE', countries=['vietnam']),
            self._make_post('GHOST', countries=['vietnam']),
        ]
        three_posts = two_posts + [self._make_post('ATLAS', countries=['vietnam'])]
        c2 = gp.build_clusters(two_posts)
        c3 = gp.build_clusters(three_posts)
        assert c3[0]['corroboration_score'] > c2[0]['corroboration_score']

    def test_critical_severity_higher_score_than_low(self):
        gp = self._make_processor()
        low_posts = [
            self._make_post('STONE', countries=['laos'], severity='LOW'),
            self._make_post('GHOST', countries=['laos'], severity='LOW'),
        ]
        critical_posts = [
            self._make_post('STONE', countries=['myanmar'], severity='CRITICAL'),
            self._make_post('GHOST', countries=['myanmar'], severity='CRITICAL'),
        ]
        c_low = gp.build_clusters(low_posts)
        c_crit = gp.build_clusters(critical_posts)
        assert c_crit[0]['corroboration_score'] > c_low[0]['corroboration_score']

    def test_clusters_sorted_by_score_descending(self):
        gp = self._make_processor()
        posts = [
            # Nigeria: 2 analysts, MEDIUM severity
            self._make_post('STONE', countries=['nigeria'], severity='MEDIUM'),
            self._make_post('GHOST', countries=['nigeria'], severity='MEDIUM'),
            # Bangladesh: 3 analysts, HIGH severity
            self._make_post('STONE', countries=['bangladesh'], sectors=['garments'], severity='HIGH', post_id='s1'),
            self._make_post('CARGO', countries=['bangladesh'], sectors=['garments'], severity='HIGH', post_id='c1'),
            self._make_post('ATLAS', countries=['bangladesh'], sectors=['garments'], severity='HIGH', post_id='a1'),
        ]
        clusters = gp.build_clusters(posts)
        scores = [c['corroboration_score'] for c in clusters]
        assert scores == sorted(scores, reverse=True)

    def test_max_50_clusters_returned(self):
        gp = self._make_processor()
        # Create many unique country pairs
        posts = []
        analysts = ['STONE', 'GHOST']
        for i in range(60):
            country = f'country{i:03d}'
            for a in analysts:
                posts.append(self._make_post(a, countries=[country], post_id=f'{a}-{i}'))
        clusters = gp.build_clusters(posts)
        assert len(clusters) <= 50

    def test_same_analyst_twice_does_not_create_cluster(self):
        gp = self._make_processor()
        posts = [
            self._make_post('STONE', countries=['ghana'], post_id='p1'),
            self._make_post('STONE', countries=['ghana'], post_id='p2'),
        ]
        clusters = gp.build_clusters(posts)
        assert clusters == []

    def test_short_entity_values_skipped(self):
        gp = self._make_processor()
        posts = [
            {'id': 'p1', 'analyst': 'STONE', 'body': '', 'confidence': 0.5,
             'entities': {'countries': ['a'], 'regions': [], 'sectors': [],
                          'asset_classes': [], 'commodities': [], 'companies': [],
                          'event_types': [], 'severity': 'LOW', 'em_relevance': 'background'}},
            {'id': 'p2', 'analyst': 'GHOST', 'body': '', 'confidence': 0.5,
             'entities': {'countries': ['a'], 'regions': [], 'sectors': [],
                          'asset_classes': [], 'commodities': [], 'companies': [],
                          'event_types': [], 'severity': 'LOW', 'em_relevance': 'background'}},
        ]
        clusters = gp.build_clusters(posts)
        assert clusters == []


# ── ENTITY_WEIGHT completeness ────────────────────────────────────────────────

class TestEntityWeights:
    def test_all_entity_types_have_weights(self):
        expected = {'countries', 'regions', 'sectors', 'commodities',
                    'event_types', 'asset_classes', 'companies'}
        assert set(ENTITY_WEIGHT.keys()) == expected

    def test_countries_highest_weight(self):
        assert ENTITY_WEIGHT['countries'] == max(ENTITY_WEIGHT.values())

    def test_all_weights_positive(self):
        for w in ENTITY_WEIGHT.values():
            assert w > 0
