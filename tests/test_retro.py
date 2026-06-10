"""
tests/test_retro.py
Unit tests for retro.py — retrospective scoring, hit rate computation,
outcome validation logic.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import uuid


@pytest.fixture
def retro_db(tmp_path):
    """Fresh DB with retro tables for each test."""
    db_file = str(tmp_path / 'retro_test.db')
    with patch.dict(os.environ, {'DATABASE_PATH': db_file, 'SUPABASE_URL': '', 'SUPABASE_KEY': ''}):
        import importlib
        import database as db_module
        importlib.reload(db_module)

        import retro as retro_module
        importlib.reload(retro_module)
        instance = retro_module.RetroScorer()
        yield instance


def _brief_id():
    return str(uuid.uuid4())


class TestRetroScorer:
    def test_validate_brief_validated(self, retro_db):
        bid = _brief_id()
        retro_db.record_outcome(bid, 'validated', 'Event confirmed by Reuters.')
        outcomes = retro_db.get_outcomes()
        assert len(outcomes) == 1
        assert outcomes[0]['outcome'] == 'validated'

    def test_validate_brief_invalidated(self, retro_db):
        bid = _brief_id()
        retro_db.record_outcome(bid, 'invalidated', 'No event occurred.')
        outcomes = retro_db.get_outcomes()
        assert outcomes[0]['outcome'] == 'invalidated'

    def test_invalid_outcome_raises(self, retro_db):
        with pytest.raises(ValueError):
            retro_db.record_outcome(_brief_id(), 'maybe', 'Not a valid outcome')

    def test_pending_outcome_allowed(self, retro_db):
        retro_db.record_outcome(_brief_id(), 'pending', '')
        outcomes = retro_db.get_outcomes()
        assert outcomes[0]['outcome'] == 'pending'

    def test_compute_hit_rate_all_validated(self, retro_db):
        for _ in range(5):
            retro_db.record_outcome(_brief_id(), 'validated', 'Confirmed.')
        stats = retro_db.compute_hit_rate()
        assert stats['hit_rate'] == pytest.approx(1.0)
        assert stats['total_resolved'] == 5

    def test_compute_hit_rate_mixed(self, retro_db):
        for _ in range(3):
            retro_db.record_outcome(_brief_id(), 'validated', '')
        for _ in range(1):
            retro_db.record_outcome(_brief_id(), 'invalidated', '')
        stats = retro_db.compute_hit_rate()
        assert stats['hit_rate'] == pytest.approx(0.75)
        assert stats['total_resolved'] == 4

    def test_compute_hit_rate_no_outcomes(self, retro_db):
        stats = retro_db.compute_hit_rate()
        assert stats['hit_rate'] is None
        assert stats['total_resolved'] == 0

    def test_pending_excluded_from_hit_rate(self, retro_db):
        retro_db.record_outcome(_brief_id(), 'validated', '')
        retro_db.record_outcome(_brief_id(), 'pending', '')
        stats = retro_db.compute_hit_rate()
        assert stats['total_resolved'] == 1

    def test_hit_rate_by_confidence_tier(self, retro_db):
        # 2 CONFIRMED validated, 0 CONFIRMED invalidated → 100% hit
        # 1 DEVELOPING invalidated → 0% hit
        retro_db.record_outcome(_brief_id(), 'validated', '', confidence_tier='CONFIRMED')
        retro_db.record_outcome(_brief_id(), 'validated', '', confidence_tier='CONFIRMED')
        retro_db.record_outcome(_brief_id(), 'invalidated', '', confidence_tier='DEVELOPING')
        by_tier = retro_db.compute_hit_rate_by_tier()
        assert by_tier['CONFIRMED']['hit_rate'] == pytest.approx(1.0)
        assert by_tier['DEVELOPING']['hit_rate'] == pytest.approx(0.0)

    def test_duplicate_outcome_for_brief_overwrites(self, retro_db):
        bid = _brief_id()
        retro_db.record_outcome(bid, 'pending', '')
        retro_db.record_outcome(bid, 'validated', 'Confirmed later.')
        outcomes = retro_db.get_outcomes(brief_id=bid)
        assert len(outcomes) == 1
        assert outcomes[0]['outcome'] == 'validated'

    def test_get_outcomes_filter_by_brief_id(self, retro_db):
        bid1, bid2 = _brief_id(), _brief_id()
        retro_db.record_outcome(bid1, 'validated', '')
        retro_db.record_outcome(bid2, 'invalidated', '')
        result = retro_db.get_outcomes(brief_id=bid1)
        assert len(result) == 1
        assert result[0]['brief_id'] == bid1

    def test_notes_stored_and_retrieved(self, retro_db):
        bid = _brief_id()
        retro_db.record_outcome(bid, 'validated', 'Cross-checked with AP wire.')
        outcomes = retro_db.get_outcomes(brief_id=bid)
        assert 'AP wire' in outcomes[0]['notes']
