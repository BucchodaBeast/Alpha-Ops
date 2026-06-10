"""
tests/test_base_agent.py
Unit tests for agents/base.py — confidence clamping, deduplication, hashing.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import MagicMock, patch
from agents.base import _clamp_confidence, _stable_hash, SOURCE_CONFIDENCE_CAP


# ── _clamp_confidence ─────────────────────────────────────────────────────────

class TestClampConfidence:
    def test_zero_sources_caps_at_20_pct(self):
        assert _clamp_confidence(0.9, 0) == pytest.approx(0.20)

    def test_one_source_caps_at_45_pct(self):
        assert _clamp_confidence(0.9, 1) == pytest.approx(0.45)

    def test_two_sources_caps_at_65_pct(self):
        assert _clamp_confidence(0.9, 2) == pytest.approx(0.65)

    def test_three_sources_caps_at_80_pct(self):
        assert _clamp_confidence(0.9, 3) == pytest.approx(0.80)

    def test_four_plus_sources_caps_at_90_pct(self):
        assert _clamp_confidence(0.95, 4) == pytest.approx(0.90)
        assert _clamp_confidence(0.95, 10) == pytest.approx(0.90)

    def test_low_confidence_below_cap_passes_through(self):
        assert _clamp_confidence(0.30, 3) == pytest.approx(0.30)

    def test_confidence_never_exceeds_1(self):
        assert _clamp_confidence(2.0, 4) <= 1.0

    def test_confidence_never_below_0(self):
        assert _clamp_confidence(-0.5, 2) == pytest.approx(0.0)

    def test_boundary_exactly_at_cap(self):
        assert _clamp_confidence(0.45, 1) == pytest.approx(0.45)

    def test_exactly_one_source_above_cap_is_clamped(self):
        assert _clamp_confidence(0.46, 1) == pytest.approx(0.45)


# ── _stable_hash ──────────────────────────────────────────────────────────────

class TestStableHash:
    def test_same_url_same_hash(self):
        item = {'title': 'Nigeria devalues naira', 'url': 'https://reuters.com/nigeria-naira'}
        assert _stable_hash(item) == _stable_hash(item)

    def test_different_urls_different_hash(self):
        a = {'title': 'Signal A', 'url': 'https://a.com/1'}
        b = {'title': 'Signal B', 'url': 'https://a.com/2'}
        assert _stable_hash(a) != _stable_hash(b)

    def test_hash_length_is_20(self):
        item = {'title': 'Test signal', 'url': 'https://example.com/test'}
        assert len(_stable_hash(item)) == 20

    def test_no_url_falls_back_to_title_source(self):
        a = {'source': 'kraken', 'title': 'BTC: $50,000', 'value': '50000'}
        b = {'source': 'kraken', 'title': 'BTC: $50,000', 'value': '50000'}
        assert _stable_hash(a) == _stable_hash(b)

    def test_title_case_insensitive(self):
        a = {'title': 'Nigeria Naira Crisis', 'url': 'https://ft.com/naira'}
        b = {'title': 'nigeria naira crisis', 'url': 'https://ft.com/naira'}
        # URL takes priority so both should match
        assert _stable_hash(a) == _stable_hash(b)

    def test_empty_item_does_not_raise(self):
        assert _stable_hash({}) is not None

    def test_private_fields_ignored_in_hash(self):
        a = {'title': 'Signal', 'url': 'https://x.com', '_hash': 'old', '_seen': True}
        b = {'title': 'Signal', 'url': 'https://x.com'}
        # _hash is computed from title+url, private fields irrelevant
        assert _stable_hash(a) == _stable_hash(b)


# ── Source confidence cap completeness ───────────────────────────────────────

class TestSourceConfidenceCap:
    def test_all_expected_source_counts_present(self):
        for count in range(5):
            assert count in SOURCE_CONFIDENCE_CAP

    def test_caps_are_monotonically_increasing(self):
        caps = [SOURCE_CONFIDENCE_CAP[i] for i in sorted(SOURCE_CONFIDENCE_CAP)]
        assert caps == sorted(caps)

    def test_no_cap_exceeds_1(self):
        for cap in SOURCE_CONFIDENCE_CAP.values():
            assert cap <= 1.0

    def test_no_cap_below_0(self):
        for cap in SOURCE_CONFIDENCE_CAP.values():
            assert cap >= 0.0


# ── BaseAgent.deduplicate (integration via mock DB) ───────────────────────────

class TestBaseAgentDeduplicate:
    def _make_agent(self, seen_hashes=None):
        """Create a minimal concrete BaseAgent with mocked DB."""
        from agents.base import BaseAgent

        class ConcreteAgent(BaseAgent):
            name = 'TEST'
            def fetch_data(self): return []

        agent = ConcreteAgent.__new__(ConcreteAgent)
        agent.name = 'TEST'
        mock_db = MagicMock()
        seen = set(seen_hashes or [])
        mock_db.check_seen.side_effect = lambda agent_name, h: h in seen
        agent.db = mock_db
        return agent

    def test_new_items_pass_through(self):
        agent = self._make_agent(seen_hashes=[])
        items = [{'title': 'New signal', 'url': 'https://ft.com/1'}]
        result = agent.deduplicate(items)
        assert len(result) == 1

    def test_seen_items_are_filtered(self):
        item = {'title': 'Seen signal', 'url': 'https://ft.com/seen'}
        h = _stable_hash(item)
        agent = self._make_agent(seen_hashes=[h])
        result = agent.deduplicate([item])
        assert len(result) == 0

    def test_mixed_items_filtered_correctly(self):
        seen_item = {'title': 'Old', 'url': 'https://ft.com/old'}
        new_item  = {'title': 'New', 'url': 'https://ft.com/new'}
        h = _stable_hash(seen_item)
        agent = self._make_agent(seen_hashes=[h])
        result = agent.deduplicate([seen_item, new_item])
        assert len(result) == 1
        assert result[0]['url'] == 'https://ft.com/new'

    def test_hash_is_attached_to_item(self):
        agent = self._make_agent()
        items = [{'title': 'Signal', 'url': 'https://ft.com/x'}]
        result = agent.deduplicate(items)
        assert '_hash' in result[0]
        assert len(result[0]['_hash']) == 20

    def test_empty_list_returns_empty(self):
        agent = self._make_agent()
        assert agent.deduplicate([]) == []


# ── BaseAgent.think — no-api-key path ────────────────────────────────────────

class TestBaseAgentThinkNoKey:
    def _make_agent(self):
        from agents.base import BaseAgent

        class ConcreteAgent(BaseAgent):
            name = 'TEST'
            display_name = 'Test'
            personality = 'Test personality'
            domain_context = 'Test domain'
            def fetch_data(self): return []

        agent = ConcreteAgent.__new__(ConcreteAgent)
        agent.name = 'TEST'
        agent.display_name = 'Test'
        agent.domain_context = 'Test domain'
        agent.db = MagicMock()
        return agent

    def test_no_api_key_produces_raw_summary(self):
        agent = self._make_agent()
        items = [{'title': 'Test signal', 'source': 'reuters', 'url': 'https://reuters.com/1'}]
        with patch('agents.base.GROQ_API_KEY', ''):
            posts = agent.think(items)
        assert len(posts) == 1
        assert posts[0]['analyst'] == 'TEST'
        assert posts[0]['confidence'] == 0.3

    def test_no_api_key_caps_at_5_items(self):
        agent = self._make_agent()
        items = [{'title': f'Signal {i}', 'source': 's', 'url': f'https://x.com/{i}'}
                 for i in range(10)]
        with patch('agents.base.GROQ_API_KEY', ''):
            posts = agent.think(items)
        assert len(posts) == 5

    def test_empty_items_returns_empty(self):
        agent = self._make_agent()
        with patch('agents.base.GROQ_API_KEY', ''):
            posts = agent.think([])
        assert posts == []
