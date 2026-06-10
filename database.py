"""
database.py — Alpha Ops Database Layer
Dual-mode: SQLite (local/dev) or Supabase (production)
Full schema: posts, briefs, seen_items, agent_runs
"""

import os
import sqlite3
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    from supabase import create_client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False

DB_PATH = os.getenv('DATABASE_PATH', 'alphaops.db')
SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY', '')

_use_supabase = HAS_SUPABASE and bool(SUPABASE_URL) and bool(SUPABASE_KEY)
_supabase_client = None


def get_supabase():
    global _supabase_client
    if _use_supabase and _supabase_client is None:
        try:
            _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as e:
            logger.error(f"Failed to create Supabase client: {e}")
            return None
    return _supabase_client


def _reset_supabase_client():
    global _supabase_client
    _supabase_client = None


@contextmanager
def _sqlite_conn():
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


def init_sqlite():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            analyst TEXT NOT NULL,
            type TEXT NOT NULL,
            body TEXT NOT NULL,
            facts TEXT DEFAULT '[]',
            inferences TEXT DEFAULT '[]',
            uncertainty_notes TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0.3,
            source_count INTEGER DEFAULT 1,
            tier TEXT DEFAULT 'free',
            timestamp TEXT,
            source_urls TEXT DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS seen_items (
            id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            hash TEXT NOT NULL UNIQUE,
            seen_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            status TEXT,
            items_found INTEGER DEFAULT 0,
            items_posted INTEGER DEFAULT 0,
            error TEXT,
            started_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS briefs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            so_what TEXT DEFAULT '',
            who_affected TEXT DEFAULT '',
            timeline TEXT DEFAULT '',
            next_steps TEXT DEFAULT '',
            what_to_watch TEXT DEFAULT '',
            confidence_tier TEXT DEFAULT 'EARLY WARNING',
            analysts_involved TEXT DEFAULT '[]',
            contributing_post_ids TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0.5,
            convergence_score REAL DEFAULT 0.5,
            brief_type TEXT DEFAULT 'convergence',
            uncertainty_notes TEXT DEFAULT '',
            tier TEXT DEFAULT 'premium',
            timestamp TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        # Indexes
        c.execute('CREATE INDEX IF NOT EXISTS idx_posts_analyst ON posts(analyst)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_posts_timestamp ON posts(timestamp DESC)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_seen_hash ON seen_items(hash)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_briefs_timestamp ON briefs(timestamp DESC)')
        conn.commit()
        logger.info("SQLite schema initialized")


class Database:
    def __init__(self):
        if not _use_supabase:
            init_sqlite()

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def check_seen(self, agent: str, item_hash: str) -> bool:
        if _use_supabase:
            try:
                sb = get_supabase()
                if not sb:
                    return False
                res = sb.table('seen_items').select('id').eq('hash', item_hash).limit(1).execute()
                return len(res.data) > 0
            except Exception as e:
                logger.warning(f"Supabase check_seen error: {e}")
                _reset_supabase_client()
                return False
        try:
            with _sqlite_conn() as conn:
                row = conn.execute(
                    'SELECT 1 FROM seen_items WHERE hash = ?', (item_hash,)
                ).fetchone()
                return row is not None
        except Exception as e:
            logger.warning(f"SQLite check_seen error: {e}")
            return False

    def mark_seen(self, agent: str, item_hash: str):
        record_id = str(uuid.uuid4())
        if _use_supabase:
            try:
                sb = get_supabase()
                if sb:
                    sb.table('seen_items').upsert({
                        'id': record_id, 'agent': agent, 'hash': item_hash
                    }).execute()
            except Exception as e:
                logger.warning(f"Supabase mark_seen error: {e}")
                _reset_supabase_client()
            return
        try:
            with _sqlite_conn() as conn:
                conn.execute(
                    'INSERT OR IGNORE INTO seen_items (id, agent, hash) VALUES (?,?,?)',
                    (record_id, agent, item_hash)
                )
        except Exception as e:
            logger.warning(f"SQLite mark_seen error: {e}")

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def insert_post(self, post: dict) -> bool:
        post_id = post.get('id') or str(uuid.uuid4())
        analyst = post.get('analyst') or post.get('citizen', 'UNKNOWN')

        def _serialize(val):
            if isinstance(val, list):
                return json.dumps(val)
            return val or '[]'

        record = {
            'id': post_id,
            'analyst': analyst,
            'type': post.get('type', 'signal'),
            'body': post.get('body', '')[:500],
            'facts': _serialize(post.get('facts', [])),
            'inferences': _serialize(post.get('inferences', [])),
            'uncertainty_notes': post.get('uncertainty_notes', ''),
            'tags': _serialize(post.get('tags', [])),
            'confidence': float(post.get('confidence', 0.3)),
            'source_count': int(post.get('source_count', 1)),
            'tier': post.get('tier', 'free'),
            'timestamp': post.get('timestamp') or datetime.now(timezone.utc).isoformat(),
            'source_urls': _serialize(post.get('source_urls', [])),
        }

        if _use_supabase:
            try:
                sb = get_supabase()
                if not sb:
                    return False
                sb.table('posts').upsert(record).execute()
                return True
            except Exception as e:
                logger.warning(f"Supabase insert_post error: {e}")
                _reset_supabase_client()
                return False

        try:
            with _sqlite_conn() as conn:
                conn.execute('''
                    INSERT OR IGNORE INTO posts
                    (id,analyst,type,body,facts,inferences,uncertainty_notes,
                     tags,confidence,source_count,tier,timestamp,source_urls)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ''', (
                    record['id'], record['analyst'], record['type'], record['body'],
                    record['facts'], record['inferences'], record['uncertainty_notes'],
                    record['tags'], record['confidence'], record['source_count'],
                    record['tier'], record['timestamp'], record['source_urls'],
                ))
                return conn.execute(
                    'SELECT changes()'
                ).fetchone()[0] > 0
        except Exception as e:
            logger.warning(f"SQLite insert_post error: {e}")
            return False

    def get_posts(self, analyst: str = None, limit: int = 50, offset: int = 0) -> list:
        if _use_supabase:
            try:
                sb = get_supabase()
                if not sb:
                    return []
                q = sb.table('posts').select('*').order('timestamp', desc=True).limit(limit).offset(offset)
                if analyst:
                    q = q.eq('analyst', analyst.upper())
                res = q.execute()
                return res.data or []
            except Exception as e:
                logger.warning(f"Supabase get_posts error: {e}")
                _reset_supabase_client()
                return []

        try:
            with _sqlite_conn() as conn:
                if analyst:
                    rows = conn.execute(
                        'SELECT * FROM posts WHERE analyst=? ORDER BY timestamp DESC LIMIT ? OFFSET ?',
                        (analyst.upper(), limit, offset)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        'SELECT * FROM posts ORDER BY timestamp DESC LIMIT ? OFFSET ?',
                        (limit, offset)
                    ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"SQLite get_posts error: {e}")
            return []

    def get_recent_posts(self, hours: int = 6) -> list:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        if _use_supabase:
            try:
                sb = get_supabase()
                if not sb:
                    return []
                res = sb.table('posts').select('*').gte('timestamp', cutoff).order('timestamp', desc=True).execute()
                return res.data or []
            except Exception as e:
                logger.warning(f"Supabase get_recent_posts error: {e}")
                _reset_supabase_client()
                return []
        try:
            with _sqlite_conn() as conn:
                rows = conn.execute(
                    'SELECT * FROM posts WHERE timestamp >= ? ORDER BY timestamp DESC',
                    (cutoff,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"SQLite get_recent_posts error: {e}")
            return []

    # ------------------------------------------------------------------
    # Briefs (SITREPs)
    # ------------------------------------------------------------------

    def insert_brief(self, brief: dict) -> bool:
        brief_id = brief.get('id') or str(uuid.uuid4())

        def _s(val):
            if isinstance(val, list):
                return json.dumps(val)
            return val or ''

        record = {
            'id': brief_id,
            'title': brief.get('title', '')[:120],
            'body': brief.get('body', '')[:800],
            'so_what': brief.get('so_what', '')[:400],
            'who_affected': brief.get('who_affected', '')[:400],
            'timeline': brief.get('timeline', '')[:300],
            'next_steps': brief.get('next_steps', '')[:400],
            'what_to_watch': brief.get('what_to_watch', '')[:400],
            'confidence_tier': brief.get('confidence_tier', 'EARLY WARNING'),
            'analysts_involved': _s(brief.get('analysts_involved', [])),
            'contributing_post_ids': _s(brief.get('contributing_post_ids', [])),
            'confidence': float(brief.get('confidence', 0.5)),
            'convergence_score': float(brief.get('convergence_score', 0.5)),
            'brief_type': brief.get('brief_type', 'convergence'),
            'uncertainty_notes': brief.get('uncertainty_notes', ''),
            'tier': brief.get('tier', 'premium'),
            'timestamp': brief.get('timestamp') or datetime.now(timezone.utc).isoformat(),
        }

        if _use_supabase:
            try:
                sb = get_supabase()
                if not sb:
                    return False
                sb.table('briefs').upsert(record).execute()
                return True
            except Exception as e:
                logger.warning(f"Supabase insert_brief error: {e}")
                _reset_supabase_client()
                return False

        try:
            with _sqlite_conn() as conn:
                conn.execute('''
                    INSERT OR IGNORE INTO briefs
                    (id,title,body,so_what,who_affected,timeline,next_steps,
                     what_to_watch,confidence_tier,analysts_involved,contributing_post_ids,
                     confidence,convergence_score,brief_type,uncertainty_notes,tier,timestamp)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ''', (
                    record['id'], record['title'], record['body'],
                    record['so_what'], record['who_affected'], record['timeline'],
                    record['next_steps'], record['what_to_watch'], record['confidence_tier'],
                    record['analysts_involved'], record['contributing_post_ids'],
                    record['confidence'], record['convergence_score'], record['brief_type'],
                    record['uncertainty_notes'], record['tier'], record['timestamp'],
                ))
                return conn.execute('SELECT changes()').fetchone()[0] > 0
        except Exception as e:
            logger.warning(f"SQLite insert_brief error: {e}")
            return False

    def get_briefs(self, limit: int = 20) -> list:
        if _use_supabase:
            try:
                sb = get_supabase()
                if not sb:
                    return []
                res = sb.table('briefs').select('*').order('timestamp', desc=True).limit(limit).execute()
                return res.data or []
            except Exception as e:
                logger.warning(f"Supabase get_briefs error: {e}")
                _reset_supabase_client()
                return []
        try:
            with _sqlite_conn() as conn:
                rows = conn.execute(
                    'SELECT * FROM briefs ORDER BY timestamp DESC LIMIT ?', (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"SQLite get_briefs error: {e}")
            return []

    # ------------------------------------------------------------------
    # Agent runs / stats
    # ------------------------------------------------------------------

    def log_agent_run(self, agent: str, status: str, items_found: int = 0,
                      items_posted: int = 0, error: str = None):
        now = datetime.now(timezone.utc).isoformat()
        if _use_supabase:
            try:
                sb = get_supabase()
                if sb:
                    sb.table('agent_runs').insert({
                        'agent': agent, 'status': status,
                        'items_found': items_found, 'items_posted': items_posted,
                        'error': error, 'completed_at': now,
                    }).execute()
            except Exception as e:
                logger.warning(f"Supabase log_agent_run error: {e}")
                _reset_supabase_client()
            return
        try:
            with _sqlite_conn() as conn:
                conn.execute('''
                    INSERT INTO agent_runs (agent,status,items_found,items_posted,error,completed_at)
                    VALUES (?,?,?,?,?,?)
                ''', (agent, status, items_found, items_posted, error, now))
        except Exception as e:
            logger.warning(f"SQLite log_agent_run error: {e}")

    def get_agent_runs(self, limit: int = 50) -> list:
        if _use_supabase:
            try:
                sb = get_supabase()
                if not sb:
                    return []
                res = sb.table('agent_runs').select('*').order('started_at', desc=True).limit(limit).execute()
                return res.data or []
            except Exception as e:
                logger.warning(f"Supabase get_agent_runs error: {e}")
                return []
        try:
            with _sqlite_conn() as conn:
                rows = conn.execute(
                    'SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ?', (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"SQLite get_agent_runs error: {e}")
            return []

    def get_stats(self) -> dict:
        if _use_supabase:
            try:
                sb = get_supabase()
                if not sb:
                    return self._empty_stats()
                total = sb.table('posts').select('id', count='exact').execute().count or 0
                briefs = sb.table('briefs').select('id', count='exact').execute().count or 0
                analysts = sb.table('posts').select('analyst').execute()
                activity = {}
                for row in (analysts.data or []):
                    a = row['analyst']
                    activity[a] = activity.get(a, 0) + 1
                return {'total_posts': total, 'total_briefs': briefs, 'analyst_activity': activity}
            except Exception as e:
                logger.warning(f"Supabase get_stats error: {e}")
                return self._empty_stats()

        try:
            with _sqlite_conn() as conn:
                total = conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
                briefs = conn.execute('SELECT COUNT(*) FROM briefs').fetchone()[0]
                rows = conn.execute(
                    'SELECT analyst, COUNT(*) as cnt FROM posts GROUP BY analyst'
                ).fetchall()
                activity = {r['analyst']: r['cnt'] for r in rows}
                return {'total_posts': total, 'total_briefs': briefs, 'analyst_activity': activity}
        except Exception as e:
            logger.warning(f"SQLite get_stats error: {e}")
            return self._empty_stats()

    def _empty_stats(self):
        return {'total_posts': 0, 'total_briefs': 0, 'analyst_activity': {}}

    # ------------------------------------------------------------------
    # Grid clusters
    # ------------------------------------------------------------------

    def _ensure_grid_tables(self):
        """Create grid/pressure tables if they don't exist yet."""
        if _use_supabase:
            return  # Supabase tables must be created via migration
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute('''CREATE TABLE IF NOT EXISTS grid_clusters (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT,
                    entity_value TEXT,
                    analysts TEXT DEFAULT '[]',
                    analyst_count INTEGER DEFAULT 0,
                    mention_count INTEGER DEFAULT 0,
                    corroboration_score REAL DEFAULT 0,
                    avg_confidence REAL DEFAULT 0,
                    max_severity TEXT DEFAULT 'LOW',
                    post_ids TEXT DEFAULT '[]',
                    sample_signals TEXT DEFAULT '[]',
                    timestamp TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )''')
                conn.execute('''CREATE TABLE IF NOT EXISTS pressure_zones (
                    id TEXT PRIMARY KEY,
                    geography TEXT NOT NULL,
                    pressure_score REAL DEFAULT 0,
                    heat_level TEXT DEFAULT 'MONITORING',
                    analyst_count INTEGER DEFAULT 0,
                    analysts TEXT DEFAULT '[]',
                    domain_count INTEGER DEFAULT 0,
                    domains TEXT DEFAULT '[]',
                    domain_diversity REAL DEFAULT 0,
                    velocity_score REAL DEFAULT 0,
                    compound_multiplier REAL DEFAULT 1,
                    cluster_count INTEGER DEFAULT 0,
                    signal_count INTEGER DEFAULT 0,
                    event_types TEXT DEFAULT '[]',
                    sectors TEXT DEFAULT '[]',
                    asset_classes TEXT DEFAULT '[]',
                    max_severity TEXT DEFAULT 'LOW',
                    post_ids TEXT DEFAULT '[]',
                    timestamp TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )''')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_grid_entity ON grid_clusters(entity_value)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_pressure_geo ON pressure_zones(geography)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_pressure_score ON pressure_zones(pressure_score DESC)')
                conn.commit()
        except Exception as e:
            logger.warning(f"_ensure_grid_tables error: {e}")

    def store_grid_clusters(self, clusters: list):
        import uuid as _uuid
        self._ensure_grid_tables()
        if not clusters:
            return

        def _s(v):
            return json.dumps(v) if isinstance(v, list) else (v or '[]')

        if _use_supabase:
            try:
                sb = get_supabase()
                if sb:
                    for c in clusters:
                        c['id'] = str(_uuid.uuid4())
                        for f in ('analysts', 'post_ids', 'sample_signals'):
                            c[f] = _s(c.get(f, []))
                    sb.table('grid_clusters').insert(clusters).execute()
            except Exception as e:
                logger.warning(f"Supabase store_grid_clusters: {e}")
            return

        try:
            with _sqlite_conn() as conn:
                # Clear old clusters before inserting fresh ones
                conn.execute("DELETE FROM grid_clusters WHERE created_at < datetime('now', '-12 hours')")
                for c in clusters:
                    rid = str(_uuid.uuid4())
                    conn.execute('''INSERT OR REPLACE INTO grid_clusters
                        (id,entity_type,entity_value,analysts,analyst_count,mention_count,
                         corroboration_score,avg_confidence,max_severity,post_ids,sample_signals,timestamp)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (
                        rid, c.get('entity_type'), c.get('entity_value'),
                        _s(c.get('analysts', [])), c.get('analyst_count', 0),
                        c.get('mention_count', 0), c.get('corroboration_score', 0),
                        c.get('avg_confidence', 0), c.get('max_severity', 'LOW'),
                        _s(c.get('post_ids', [])), _s(c.get('sample_signals', [])),
                        c.get('timestamp', datetime.now(timezone.utc).isoformat()),
                    ))
        except Exception as e:
            logger.warning(f"SQLite store_grid_clusters: {e}")

    def get_grid_clusters(self, limit: int = 200) -> list:
        self._ensure_grid_tables()
        if _use_supabase:
            try:
                sb = get_supabase()
                if not sb:
                    return []
                res = sb.table('grid_clusters').select('*').order('corroboration_score', desc=True).limit(limit).execute()
                return res.data or []
            except Exception as e:
                logger.warning(f"Supabase get_grid_clusters: {e}")
                return []
        try:
            with _sqlite_conn() as conn:
                rows = conn.execute(
                    'SELECT * FROM grid_clusters ORDER BY corroboration_score DESC LIMIT ?', (limit,)
                ).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    for f in ('analysts', 'post_ids', 'sample_signals'):
                        if isinstance(d.get(f), str):
                            try:
                                d[f] = json.loads(d[f])
                            except Exception:
                                d[f] = []
                    result.append(d)
                return result
        except Exception as e:
            logger.warning(f"SQLite get_grid_clusters: {e}")
            return []

    # ------------------------------------------------------------------
    # Pressure zones
    # ------------------------------------------------------------------

    def store_pressure_zones(self, zones: list):
        import uuid as _uuid
        self._ensure_grid_tables()
        if not zones:
            return

        def _s(v):
            return json.dumps(v) if isinstance(v, list) else (v or '[]')

        if _use_supabase:
            try:
                sb = get_supabase()
                if sb:
                    for z in zones:
                        z['id'] = str(_uuid.uuid4())
                        for f in ('analysts','domains','event_types','sectors','asset_classes','post_ids'):
                            z[f] = _s(z.get(f, []))
                    sb.table('pressure_zones').delete().neq('id', 'none').execute()
                    sb.table('pressure_zones').insert(zones).execute()
            except Exception as e:
                logger.warning(f"Supabase store_pressure_zones: {e}")
            return

        try:
            with _sqlite_conn() as conn:
                conn.execute("DELETE FROM pressure_zones")
                for z in zones:
                    rid = str(_uuid.uuid4())
                    conn.execute('''INSERT INTO pressure_zones
                        (id,geography,pressure_score,heat_level,analyst_count,analysts,
                         domain_count,domains,domain_diversity,velocity_score,compound_multiplier,
                         cluster_count,signal_count,event_types,sectors,asset_classes,
                         max_severity,post_ids,timestamp)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                        rid, z.get('geography'), z.get('pressure_score', 0),
                        z.get('heat_level', 'MONITORING'), z.get('analyst_count', 0),
                        _s(z.get('analysts', [])), z.get('domain_count', 0),
                        _s(z.get('domains', [])), z.get('domain_diversity', 0),
                        z.get('velocity_score', 0), z.get('compound_multiplier', 1),
                        z.get('cluster_count', 0), z.get('signal_count', 0),
                        _s(z.get('event_types', [])), _s(z.get('sectors', [])),
                        _s(z.get('asset_classes', [])), z.get('max_severity', 'LOW'),
                        _s(z.get('post_ids', [])),
                        z.get('timestamp', datetime.now(timezone.utc).isoformat()),
                    ))
        except Exception as e:
            logger.warning(f"SQLite store_pressure_zones: {e}")

    def get_pressure_zones(self, limit: int = 30) -> list:
        self._ensure_grid_tables()
        if _use_supabase:
            try:
                sb = get_supabase()
                if not sb:
                    return []
                res = sb.table('pressure_zones').select('*').order('pressure_score', desc=True).limit(limit).execute()
                return res.data or []
            except Exception as e:
                logger.warning(f"Supabase get_pressure_zones: {e}")
                return []
        try:
            with _sqlite_conn() as conn:
                rows = conn.execute(
                    'SELECT * FROM pressure_zones ORDER BY pressure_score DESC LIMIT ?', (limit,)
                ).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    for f in ('analysts','domains','event_types','sectors','asset_classes','post_ids'):
                        if isinstance(d.get(f), str):
                            try:
                                d[f] = json.loads(d[f])
                            except Exception:
                                d[f] = []
                    result.append(d)
                return result
        except Exception as e:
            logger.warning(f"SQLite get_pressure_zones: {e}")
            return []
