"""
retro.py — Alpha Ops Retrospective Scoring Engine

Tracks SITREP / NEXUS Brief outcomes over time.
Answers the key question: is this system actually right?

Each brief can be marked:
  - pending    → awaiting outcome (default)
  - validated  → event occurred as predicted
  - invalidated → event did not occur / prediction was wrong
  - partial    → some elements correct, some not

Hit rate = validated / (validated + invalidated)
Tracked globally and broken down by confidence tier.
"""

import os
import sqlite3
import uuid
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.getenv('DATABASE_PATH', 'alphaops.db')

VALID_OUTCOMES = {'pending', 'validated', 'invalidated', 'partial'}


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS brief_outcomes (
                id          TEXT PRIMARY KEY,
                brief_id    TEXT NOT NULL UNIQUE,
                outcome     TEXT NOT NULL DEFAULT 'pending',
                notes       TEXT DEFAULT '',
                confidence_tier TEXT DEFAULT '',
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_outcomes_brief ON brief_outcomes(brief_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_outcomes_outcome ON brief_outcomes(outcome)')
        conn.commit()


class RetroScorer:
    """Records and computes retrospective accuracy for NEXUS Briefs."""

    def __init__(self):
        _ensure_table()

    def record_outcome(self, brief_id: str, outcome: str, notes: str,
                       confidence_tier: str = '') -> dict:
        """
        Record or update the outcome for a brief.
        outcome must be one of: pending, validated, invalidated, partial
        """
        if outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"Invalid outcome '{outcome}'. Must be one of: {VALID_OUTCOMES}"
            )
        now = datetime.now(timezone.utc).isoformat()
        record_id = str(uuid.uuid4())

        try:
            with _conn() as conn:
                # UPSERT: if brief_id exists, update; otherwise insert
                existing = conn.execute(
                    'SELECT id FROM brief_outcomes WHERE brief_id = ?', (brief_id,)
                ).fetchone()

                if existing:
                    conn.execute('''
                        UPDATE brief_outcomes
                        SET outcome=?, notes=?, confidence_tier=?, updated_at=?
                        WHERE brief_id=?
                    ''', (outcome, notes, confidence_tier, now, brief_id))
                else:
                    conn.execute('''
                        INSERT INTO brief_outcomes
                        (id, brief_id, outcome, notes, confidence_tier, recorded_at, updated_at)
                        VALUES (?,?,?,?,?,?,?)
                    ''', (record_id, brief_id, outcome, notes, confidence_tier, now, now))

            return {'brief_id': brief_id, 'outcome': outcome, 'notes': notes}
        except Exception as e:
            logger.error(f"[RETRO] record_outcome failed: {e}")
            raise

    def get_outcomes(self, brief_id: str = None, outcome_filter: str = None) -> list:
        """Retrieve outcomes, optionally filtered by brief_id or outcome type."""
        try:
            with _conn() as conn:
                if brief_id:
                    rows = conn.execute(
                        'SELECT * FROM brief_outcomes WHERE brief_id=? ORDER BY updated_at DESC',
                        (brief_id,)
                    ).fetchall()
                elif outcome_filter:
                    rows = conn.execute(
                        'SELECT * FROM brief_outcomes WHERE outcome=? ORDER BY updated_at DESC',
                        (outcome_filter,)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        'SELECT * FROM brief_outcomes ORDER BY updated_at DESC'
                    ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[RETRO] get_outcomes failed: {e}")
            return []

    def compute_hit_rate(self) -> dict:
        """
        Compute overall hit rate across all resolved outcomes.
        Returns: {hit_rate, validated, invalidated, partial, total_resolved, total_pending}
        hit_rate is None if no resolved outcomes exist yet.
        """
        try:
            with _conn() as conn:
                rows = conn.execute(
                    '''SELECT outcome, COUNT(*) as cnt
                       FROM brief_outcomes
                       GROUP BY outcome'''
                ).fetchall()

            counts = {r['outcome']: r['cnt'] for r in rows}
            validated   = counts.get('validated', 0)
            invalidated = counts.get('invalidated', 0)
            partial     = counts.get('partial', 0)
            pending     = counts.get('pending', 0)

            # partial counts as 0.5 hit
            resolved = validated + invalidated + partial
            if resolved == 0:
                hit_rate = None
            else:
                hit_rate = round((validated + partial * 0.5) / resolved, 4)

            return {
                'hit_rate': hit_rate,
                'validated': validated,
                'invalidated': invalidated,
                'partial': partial,
                'total_resolved': resolved,
                'total_pending': pending,
            }
        except Exception as e:
            logger.error(f"[RETRO] compute_hit_rate failed: {e}")
            return {'hit_rate': None, 'total_resolved': 0, 'total_pending': 0}

    def compute_hit_rate_by_tier(self) -> dict:
        """
        Compute hit rate broken down by confidence tier.
        Returns: {'CONFIRMED': {'hit_rate': 0.8, 'total_resolved': 10}, ...}
        """
        try:
            with _conn() as conn:
                rows = conn.execute(
                    '''SELECT confidence_tier, outcome, COUNT(*) as cnt
                       FROM brief_outcomes
                       WHERE confidence_tier != '' AND outcome != 'pending'
                       GROUP BY confidence_tier, outcome'''
                ).fetchall()

            # Aggregate by tier
            tiers: dict = {}
            for row in rows:
                tier = row['confidence_tier']
                outcome = row['outcome']
                cnt = row['cnt']
                if tier not in tiers:
                    tiers[tier] = {'validated': 0, 'invalidated': 0, 'partial': 0}
                tiers[tier][outcome] = tiers[tier].get(outcome, 0) + cnt

            result = {}
            for tier, counts in tiers.items():
                v = counts.get('validated', 0)
                inv = counts.get('invalidated', 0)
                p = counts.get('partial', 0)
                resolved = v + inv + p
                result[tier] = {
                    'hit_rate': round((v + p * 0.5) / resolved, 4) if resolved else None,
                    'validated': v,
                    'invalidated': inv,
                    'partial': p,
                    'total_resolved': resolved,
                }
            return result
        except Exception as e:
            logger.error(f"[RETRO] compute_hit_rate_by_tier failed: {e}")
            return {}

    def get_summary(self) -> dict:
        """Full summary for the /api/retro/summary endpoint."""
        overall = self.compute_hit_rate()
        by_tier = self.compute_hit_rate_by_tier()
        recent = self.get_outcomes()[:10]
        return {
            'overall': overall,
            'by_confidence_tier': by_tier,
            'recent_outcomes': recent,
        }
