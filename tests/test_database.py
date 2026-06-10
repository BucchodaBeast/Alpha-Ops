"""
tests/test_database.py
Integration tests for database.py — SQLite mode only (no Supabase needed).
Tests schema init, CRUD ops, dedup, stats, grid/pressure tables.
"""

import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch


@pytest.fixture
def db(tmp_path):
    """Fresh in-memory database for each test."""
    db_file = str(tmp_path / 'test_alphaops.db')
    with patch.dict(os.environ, {'DATABASE_PATH': db_file, 'SUPABASE_URL': '', 'SUPABASE_KEY': ''}):
        # Re-import with patched env
        import importlib
        import database as db_module
        importlib.reload(db_module)
        instance = db_module.Database()
        yield instance


# ── Seen items / deduplication ────────────────────────────────────────────────

class TestSeenItems:
    def test_new_hash_not_seen(self, db):
        assert db.check_seen('STONE', 'abc123') is False

    def test_marked_hash_is_seen(self, db):
        db.mark_seen('STONE', 'abc123')
        assert db.check_seen('STONE', 'abc123') is True

    def test_different_hash_not_seen(self, db):
        db.mark_seen('STONE', 'abc123')
        assert db.check_seen('STONE', 'xyz789') is False

    def test_duplicate_mark_does_not_raise(self, db):
        db.mark_seen('STONE', 'dup123')
        db.mark_seen('STONE', 'dup123')  # should not raise


# ── Posts ─────────────────────────────────────────────────────────────────────

class TestPosts:
    def _make_post(self, analyst='STONE', post_type='signal', confidence=0.5):
        return {
            'id': str(uuid.uuid4()),
            'analyst': analyst,
            'type': post_type,
            'body': f'Test signal from {analyst}',
            'facts': ['Fact 1', 'Fact 2'],
            'inferences': ['Inference: something may follow'],
            'tags': ['nigeria', 'currency'],
            'confidence': confidence,
            'source_count': 2,
            'uncertainty_notes': 'Limited data.',
            'tier': 'free',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'source_urls': ['https://ft.com/test'],
        }

    def test_insert_and_retrieve_post(self, db):
        post = self._make_post()
        assert db.insert_post(post) is True
        posts = db.get_posts()
        assert len(posts) == 1
        assert posts[0]['analyst'] == 'STONE'

    def test_duplicate_post_not_inserted_twice(self, db):
        post = self._make_post()
        db.insert_post(post)
        db.insert_post(post)  # same id
        assert len(db.get_posts()) == 1

    def test_filter_by_analyst(self, db):
        db.insert_post(self._make_post('STONE'))
        db.insert_post(self._make_post('GHOST'))
        stone_posts = db.get_posts(analyst='STONE')
        assert all(p['analyst'] == 'STONE' for p in stone_posts)
        assert len(stone_posts) == 1

    def test_limit_respected(self, db):
        for _ in range(10):
            db.insert_post(self._make_post())
        posts = db.get_posts(limit=3)
        assert len(posts) <= 3

    def test_get_recent_posts_returns_within_window(self, db):
        post = self._make_post()
        db.insert_post(post)
        recent = db.get_recent_posts(hours=1)
        assert len(recent) == 1

    def test_body_truncated_at_500(self, db):
        post = self._make_post()
        post['body'] = 'x' * 1000
        db.insert_post(post)
        stored = db.get_posts()[0]
        assert len(stored['body']) <= 500


# ── Briefs ────────────────────────────────────────────────────────────────────

class TestBriefs:
    def _make_brief(self):
        return {
            'id': str(uuid.uuid4()),
            'title': 'Nigeria Currency Crisis Convergence',
            'body': 'STONE, GHOST, and ATLAS independently flagged NGN stress.',
            'so_what': 'Frontier fund managers should reduce NGN exposure.',
            'who_affected': 'Frontier equities, NGN-denominated bonds',
            'timeline': '7-14 days',
            'next_steps': '1. Monitor NGN/USD. 2. Check CBN reserves.',
            'what_to_watch': '1. CBN intervention. 2. FX reserves.',
            'confidence_tier': 'CONFIRMED',
            'analysts_involved': ['STONE', 'GHOST', 'ATLAS'],
            'contributing_post_ids': ['p1', 'p2', 'p3'],
            'confidence': 0.72,
            'convergence_score': 0.68,
            'brief_type': 'convergence',
            'uncertainty_notes': 'CBN data lag 48h.',
            'tier': 'premium',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    def test_insert_and_retrieve_brief(self, db):
        brief = self._make_brief()
        assert db.insert_brief(brief) is True
        briefs = db.get_briefs()
        assert len(briefs) == 1
        assert briefs[0]['title'] == 'Nigeria Currency Crisis Convergence'

    def test_confidence_tier_stored_correctly(self, db):
        brief = self._make_brief()
        db.insert_brief(brief)
        stored = db.get_briefs()[0]
        assert stored['confidence_tier'] == 'CONFIRMED'

    def test_duplicate_brief_not_duplicated(self, db):
        brief = self._make_brief()
        db.insert_brief(brief)
        db.insert_brief(brief)
        assert len(db.get_briefs()) == 1


# ── Agent runs / stats ────────────────────────────────────────────────────────

class TestAgentRuns:
    def test_log_and_retrieve_run(self, db):
        db.log_agent_run('STONE', 'success', items_found=5, items_posted=3)
        runs = db.get_agent_runs()
        assert len(runs) >= 1
        assert runs[0]['agent'] == 'STONE'
        assert runs[0]['status'] == 'success'

    def test_error_run_stored(self, db):
        db.log_agent_run('GRID', 'error', error='Timeout')
        runs = db.get_agent_runs()
        assert runs[0]['error'] == 'Timeout'

    def test_stats_counts_correctly(self, db):
        post_id = str(uuid.uuid4())
        db.insert_post({
            'id': post_id, 'analyst': 'STONE', 'type': 'signal',
            'body': 'Test', 'confidence': 0.4, 'source_count': 1,
            'tier': 'free', 'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        stats = db.get_stats()
        assert stats['total_posts'] == 1
        assert stats['analyst_activity']['STONE'] == 1

    def test_empty_stats_safe(self, db):
        stats = db.get_stats()
        assert stats['total_posts'] == 0
        assert stats['total_briefs'] == 0


# ── Grid / Pressure tables ────────────────────────────────────────────────────

class TestGridPressureTables:
    def _make_cluster(self, entity='nigeria', analysts=None):
        return {
            'entity_type': 'countries',
            'entity_value': entity,
            'analysts': analysts or ['STONE', 'GHOST'],
            'analyst_count': 2,
            'mention_count': 3,
            'corroboration_score': 4.5,
            'avg_confidence': 0.55,
            'max_severity': 'MEDIUM',
            'post_ids': ['p1', 'p2'],
            'sample_signals': ['Signal A', 'Signal B'],
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    def _make_zone(self, geography='nigeria'):
        return {
            'geography': geography,
            'pressure_score': 7.2,
            'heat_level': 'HIGH',
            'analyst_count': 3,
            'analysts': ['STONE', 'GHOST', 'ATLAS'],
            'domain_count': 3,
            'domains': ['financial', 'conflict', 'geopolitical'],
            'domain_diversity': 1.8,
            'velocity_score': 2.1,
            'compound_multiplier': 1.5,
            'cluster_count': 4,
            'signal_count': 8,
            'event_types': ['currency crisis', 'conflict escalation'],
            'sectors': ['oil & gas'],
            'asset_classes': ['frontier equities'],
            'max_severity': 'HIGH',
            'post_ids': ['p1', 'p2', 'p3'],
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    def test_store_and_retrieve_clusters(self, db):
        db.store_grid_clusters([self._make_cluster()])
        clusters = db.get_grid_clusters()
        assert len(clusters) == 1
        assert clusters[0]['entity_value'] == 'nigeria'

    def test_cluster_analysts_deserialized_as_list(self, db):
        db.store_grid_clusters([self._make_cluster()])
        clusters = db.get_grid_clusters()
        assert isinstance(clusters[0]['analysts'], list)

    def test_store_and_retrieve_pressure_zones(self, db):
        db.store_pressure_zones([self._make_zone()])
        zones = db.get_pressure_zones()
        assert len(zones) == 1
        assert zones[0]['geography'] == 'nigeria'

    def test_pressure_zones_replace_on_store(self, db):
        db.store_pressure_zones([self._make_zone('nigeria')])
        db.store_pressure_zones([self._make_zone('ghana')])
        zones = db.get_pressure_zones()
        geographies = [z['geography'] for z in zones]
        assert 'nigeria' not in geographies
        assert 'ghana' in geographies
