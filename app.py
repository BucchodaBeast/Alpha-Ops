"""
app.py — Alpha Ops Intelligence Platform
Flask backend + APScheduler with staggered agent intervals
"""

import os
import json
import logging
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(32).hex())

FRONTEND_URL = os.getenv('FRONTEND_URL', '')
allowed_origins = ['http://localhost:3000', 'http://127.0.0.1:5000']
if FRONTEND_URL:
    allowed_origins.append(FRONTEND_URL)
# Also allow all github.io subdomains pattern — use explicit URL via env var
CORS(app, origins=allowed_origins, supports_credentials=False)

ADMIN_API_KEY = os.getenv('ADMIN_API_KEY', '')

# ── Agent imports ─────────────────────────────────────────────────────────────
def _load_agents():
    agents = {}
    try:
        from agents.stone import StoneAgent
        agents['STONE'] = StoneAgent()
    except Exception as e:
        logger.error(f"Failed to load STONE: {e}")
    try:
        from agents.voss import VossAgent
        agents['VOSS'] = VossAgent()
    except Exception as e:
        logger.error(f"Failed to load VOSS: {e}")
    try:
        from agents.mara import MaraAgent
        agents['MARA'] = MaraAgent()
    except Exception as e:
        logger.error(f"Failed to load MARA: {e}")
    try:
        from agents.reed import ReedAgent
        agents['REED'] = ReedAgent()
    except Exception as e:
        logger.error(f"Failed to load REED: {e}")
    try:
        from agents.atlas_watt_tide_echo_lex import (
            AtlasAgent, WattAgent, TideAgent, EchoAgent, LexAgent
        )
        agents['ATLAS'] = AtlasAgent()
        agents['WATT'] = WattAgent()
        agents['TIDE'] = TideAgent()
        agents['ECHO'] = EchoAgent()
        agents['LEX'] = LexAgent()
    except Exception as e:
        logger.error(f"Failed to load ATLAS/WATT/TIDE/ECHO/LEX: {e}")
    try:
        from agents.finn_cargo_terra_delphi_ghost import (
            FinnAgent, CargoAgent, TerraAgent, DelphiAgent, GhostAgent
        )
        agents['FINN'] = FinnAgent()
        agents['CARGO'] = CargoAgent()
        agents['TERRA'] = TerraAgent()
        agents['DELPHI'] = DelphiAgent()
        agents['GHOST'] = GhostAgent()
    except Exception as e:
        logger.error(f"Failed to load FINN/CARGO/TERRA/DELPHI/GHOST: {e}")
    try:
        from agents.desk import DeskAgent
        agents['DESK'] = DeskAgent()
    except Exception as e:
        logger.error(f"Failed to load DESK: {e}")
    try:
        from agents.grid import GridProcessor
        agents['GRID'] = GridProcessor()
    except Exception as e:
        logger.error(f"Failed to load GRID: {e}")
    try:
        from agents.pressure import PressureProcessor
        agents['PRESSURE'] = PressureProcessor()
    except Exception as e:
        logger.error(f"Failed to load PRESSURE: {e}")
    return agents


AGENTS = _load_agents()
logger.info(f"Loaded agents: {list(AGENTS.keys())}")

# ── Database ──────────────────────────────────────────────────────────────────
from database import Database
db = Database()

# ── Auth ──────────────────────────────────────────────────────────────────────
def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if ADMIN_API_KEY:
            key = request.headers.get('X-Admin-Key', '')
            if key != ADMIN_API_KEY:
                return jsonify({'error': 'Unauthorized'}), 403
        return f(*args, **kwargs)
    return decorated

# ── Scheduler ─────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(daemon=True)
_scheduler_lock = threading.Lock()

def _run_agent(name: str):
    agent = AGENTS.get(name)
    if not agent:
        return
    with _scheduler_lock:
        try:
            count = agent.run()
            logger.info(f"[SCHEDULER] {name} → {count} posts")
        except Exception as e:
            logger.error(f"[SCHEDULER] {name} failed: {e}")

# Staggered intervals (minutes) — spread across hour to avoid Groq burst
AGENT_INTERVALS = {
    'STONE':  20,   # Markets — fairly frequent
    'GHOST':  40,   # Conflict — moderate
    'ATLAS':  30,   # Geopolitics — moderate
    'MARA':   45,   # Health — slower changing
    'TIDE':   50,   # Maritime — slower
    'ECHO':   40,   # Social — moderate
    'VOSS':   35,   # Insider — moderate
    'TERRA':  80,   # Climate — slow
    'WATT':   60,   # Energy — moderate
    'LEX':    55,   # Regulatory — slow
    'CARGO':  65,   # Supply chain — slow
    'FINN':   75,   # Investment signals — slow
    'REED':   90,   # Research — slowest
    'DELPHI': 85,   # Prediction markets — slow
    'DESK':   25,   # Synthesis — runs often to catch convergences
    'GRID':   15,   # Entity extraction — runs frequently
    'PRESSURE': 20, # Pressure scoring — runs frequently
}

# Stagger start delays so agents don't all fire at once
START_DELAYS = {
    'STONE':  0,
    'ATLAS':  2,
    'VOSS':   4,
    'ECHO':   6,
    'GHOST':  8,
    'MARA':   10,
    'WATT':   12,
    'TIDE':   14,
    'LEX':    16,
    'CARGO':  18,
    'TERRA':  20,
    'FINN':   22,
    'DELPHI': 24,
    'REED':   26,
    'DESK':   30,  # DESK runs after initial wave
    'GRID':   12,  # Grid runs after first wave of signals
    'PRESSURE': 18, # Pressure runs after Grid
}


def start_scheduler():
    if scheduler.running:
        return
    for name, interval in AGENT_INTERVALS.items():
        delay = START_DELAYS.get(name, 0)
        scheduler.add_job(
            _run_agent,
            'interval',
            minutes=interval,
            args=[name],
            id=f'agent_{name}',
            replace_existing=True,
            misfire_grace_time=120,
            max_instances=1,
        )
    scheduler.start()
    logger.info("Scheduler started with staggered agent intervals")

    # Fire initial wave in background threads with delays
    def _delayed_fire(name, delay_seconds):
        import time
        time.sleep(delay_seconds)
        _run_agent(name)

    for name, delay_mins in START_DELAYS.items():
        t = threading.Thread(
            target=_delayed_fire,
            args=[name, delay_mins * 60],
            daemon=True
        )
        t.start()

# ── API Routes ────────────────────────────────────────────────────────────────

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'operational',
        'agents': list(AGENTS.keys()),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })


@app.route('/api/posts')
def get_posts():
    analyst = request.args.get('analyst', '').upper() or None
    limit = min(int(request.args.get('limit', 50)), 200)
    offset = int(request.args.get('offset', 0))
    posts = db.get_posts(analyst=analyst, limit=limit, offset=offset)

    # Deserialize JSON fields for frontend
    for post in posts:
        for field in ('tags', 'source_urls', 'facts', 'inferences'):
            val = post.get(field)
            if isinstance(val, str):
                try:
                    post[field] = json.loads(val)
                except Exception:
                    post[field] = []

    return jsonify({'posts': posts, 'count': len(posts)})


@app.route('/api/briefs')
def get_briefs():
    limit = min(int(request.args.get('limit', 20)), 100)
    briefs = db.get_briefs(limit=limit)

    for brief in briefs:
        for field in ('analysts_involved', 'contributing_post_ids'):
            val = brief.get(field)
            if isinstance(val, str):
                try:
                    brief[field] = json.loads(val)
                except Exception:
                    brief[field] = []

    return jsonify({'briefs': briefs, 'count': len(briefs)})


@app.route('/api/stats')
def get_stats():
    stats = db.get_stats()
    agent_meta = {}
    for name, agent in AGENTS.items():
        agent_meta[name] = {
            'display_name': getattr(agent, 'display_name', name),
            'personality': getattr(agent, 'personality', '')[:100],
            'interval_minutes': AGENT_INTERVALS.get(name, 60),
        }
    return jsonify({**stats, 'agent_meta': agent_meta})


@app.route('/api/agents')
def get_agents():
    agents_info = []
    activity = db.get_stats().get('analyst_activity', {})
    for name, agent in AGENTS.items():
        agents_info.append({
            'name': name,
            'display_name': getattr(agent, 'display_name', name),
            'personality': getattr(agent, 'personality', ''),
            'domain_context': getattr(agent, 'domain_context', '')[:200],
            'interval_minutes': AGENT_INTERVALS.get(name, 60),
            'post_count': activity.get(name, 0),
        })
    return jsonify({'agents': agents_info})


@app.route('/api/trigger/<agent_name>', methods=['POST'])
@require_admin
def trigger_agent(agent_name: str):
    name = agent_name.upper()
    agent = AGENTS.get(name)
    if not agent:
        return jsonify({'error': f'Agent {name} not found'}), 404

    def _run():
        _run_agent(name)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'status': 'triggered', 'agent': name})


@app.route('/api/trigger/all', methods=['POST'])
@require_admin
def trigger_all():
    triggered = []
    for name in AGENTS:
        t = threading.Thread(target=_run_agent, args=[name], daemon=True)
        t.start()
        triggered.append(name)
    return jsonify({'status': 'triggered', 'agents': triggered})


@app.route('/api/runs')
@require_admin
def get_runs():
    runs = db.get_agent_runs(limit=100)
    return jsonify({'runs': runs})


@app.route('/')
def index():
    return jsonify({
        'service': 'Alpha Ops Intelligence Platform',
        'version': '2.0',
        'status': 'operational',
        'docs': '/api/health',
    })


# ── Boot ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    start_scheduler()
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    # Gunicorn / Render
    start_scheduler()

# ── Grid + Pressure routes ────────────────────────────────────────────────────

@app.route('/api/grid')
def get_grid():
    clusters = db.get_grid_clusters(limit=100)
    for c in clusters:
        for f in ('analysts', 'post_ids', 'sample_signals'):
            if isinstance(c.get(f), str):
                try: c[f] = json.loads(c[f])
                except: c[f] = []
    return jsonify({'clusters': clusters, 'count': len(clusters)})


@app.route('/api/pressure')
def get_pressure():
    zones = db.get_pressure_zones(limit=30)
    for z in zones:
        for f in ('analysts','domains','event_types','sectors','asset_classes','post_ids'):
            if isinstance(z.get(f), str):
                try: z[f] = json.loads(z[f])
                except: z[f] = []
    return jsonify({'zones': zones, 'count': len(zones)})


# ═══════════════════════════════════════════════════════════════════════════════
# ADDITIONS: Auth, Retrospective Scoring, SSE, Agent Trace
# ═══════════════════════════════════════════════════════════════════════════════

import queue
import time as _time
from retro import RetroScorer
import auth as _auth

_retro = RetroScorer()

# ── SSE Event Bus ─────────────────────────────────────────────────────────────
# Lightweight pub/sub for server-sent events. Max 50 subscribers.

_sse_subscribers: list[queue.Queue] = []
_sse_lock = threading.Lock()
_SSE_MAX_SUBSCRIBERS = 50


def _publish_event(event_type: str, data: dict):
    """Broadcast an SSE event to all connected clients."""
    import json as _json
    payload = f"event: {event_type}\ndata: {_json.dumps(data)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)


def _patch_agent_run_for_sse():
    """Monkey-patch _run_agent to broadcast SSE events after each run."""
    original = globals()['_run_agent']

    def patched(name: str):
        original(name)
        _publish_event('agent_run', {
            'agent': name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        # Also broadcast latest stats
        try:
            stats = db.get_stats()
            _publish_event('stats_update', stats)
        except Exception:
            pass

    globals()['_run_agent'] = patched


_patch_agent_run_for_sse()


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route('/api/auth/register', methods=['POST'])
def register():
    body = request.get_json(silent=True) or {}
    email    = (body.get('email') or '').strip()
    password = body.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'email and password are required'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    try:
        user = _auth.register_user(email, password)
        token = _auth.create_token(user['id'], user['email'])
        return jsonify({'token': token, 'user': user}), 201
    except _auth.UserExistsError:
        return jsonify({'error': 'Email already registered'}), 409
    except Exception as e:
        logger.error(f"[AUTH] register error: {e}")
        return jsonify({'error': 'Registration failed'}), 500


@app.route('/api/auth/login', methods=['POST'])
def login():
    body = request.get_json(silent=True) or {}
    email    = (body.get('email') or '').strip()
    password = body.get('password') or ''
    try:
        result = _auth.login(email, password)
        return jsonify(result)
    except _auth.InvalidCredentialsError:
        return jsonify({'error': 'Invalid email or password'}), 401
    except Exception as e:
        logger.error(f"[AUTH] login error: {e}")
        return jsonify({'error': 'Login failed'}), 500


@app.route('/api/auth/me')
@_auth.require_auth
def me():
    user = _auth.get_user_by_id(request.user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'user': user})


# ── Watchlist routes ──────────────────────────────────────────────────────────

@app.route('/api/watchlist', methods=['GET'])
@_auth.require_auth
def get_watchlist():
    wl = _auth.get_watchlist(request.user_id)
    return jsonify(wl)


@app.route('/api/watchlist', methods=['PUT'])
@_auth.require_auth
def update_watchlist():
    body = request.get_json(silent=True) or {}
    updated = _auth.update_watchlist(
        request.user_id,
        countries=body.get('countries'),
        sectors=body.get('sectors'),
        analysts=body.get('analysts'),
    )
    return jsonify(updated)


@app.route('/api/watchlist/feed')
@_auth.require_auth
def watchlist_feed():
    """Return posts and briefs filtered to user's watchlist."""
    wl = _auth.get_watchlist(request.user_id)
    limit = min(int(request.args.get('limit', 30)), 100)

    all_posts = db.get_posts(limit=200)
    filtered = []
    countries_lower = [c.lower() for c in wl.get('countries', [])]
    sectors_lower   = [s.lower() for s in wl.get('sectors', [])]
    analysts_upper  = [a.upper() for a in wl.get('analysts', [])]

    for post in all_posts:
        # Analyst filter
        if analysts_upper and post.get('analyst') in analysts_upper:
            filtered.append(post)
            continue
        # Tag-based country/sector filter
        tags = post.get('tags', [])
        if isinstance(tags, str):
            try: tags = json.loads(tags)
            except: tags = []
        tags_lower = [str(t).lower() for t in tags]
        if any(c in tags_lower for c in countries_lower):
            filtered.append(post)
            continue
        if any(s in tags_lower for s in sectors_lower):
            filtered.append(post)
            continue

    # Deserialize JSON fields
    for post in filtered:
        for field in ('tags', 'source_urls', 'facts', 'inferences'):
            val = post.get(field)
            if isinstance(val, str):
                try: post[field] = json.loads(val)
                except: post[field] = []

    return jsonify({'posts': filtered[:limit], 'count': len(filtered[:limit]), 'watchlist': wl})


# ── Retrospective scoring routes ──────────────────────────────────────────────

@app.route('/api/retro/summary')
def retro_summary():
    """Public: system-wide accuracy summary."""
    return jsonify(_retro.get_summary())


@app.route('/api/retro/outcomes', methods=['GET'])
def get_retro_outcomes():
    outcomes = _retro.get_outcomes()
    return jsonify({'outcomes': outcomes, 'count': len(outcomes)})


@app.route('/api/retro/outcomes', methods=['POST'])
@require_admin
def record_retro_outcome():
    """Admin: record or update outcome for a brief."""
    body = request.get_json(silent=True) or {}
    brief_id = body.get('brief_id', '').strip()
    outcome  = body.get('outcome', '').strip()
    notes    = body.get('notes', '').strip()
    confidence_tier = body.get('confidence_tier', '').strip()

    if not brief_id or not outcome:
        return jsonify({'error': 'brief_id and outcome are required'}), 400

    try:
        result = _retro.record_outcome(brief_id, outcome, notes, confidence_tier)
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"[RETRO] POST error: {e}")
        return jsonify({'error': 'Failed to record outcome'}), 500


@app.route('/api/retro/hit-rate')
def retro_hit_rate():
    overall = _retro.compute_hit_rate()
    by_tier = _retro.compute_hit_rate_by_tier()
    return jsonify({'overall': overall, 'by_confidence_tier': by_tier})


# ── Agent trace / observability ───────────────────────────────────────────────

@app.route('/api/agents/<agent_name>/trace')
@require_admin
def agent_trace(agent_name: str):
    """
    Admin: full observability trace for a named agent.
    Returns: recent runs, recent posts, agent metadata, interval config.
    """
    name = agent_name.upper()
    agent = AGENTS.get(name)
    if not agent:
        return jsonify({'error': f'Agent {name} not found'}), 404

    runs = db.get_agent_runs(limit=100)
    agent_runs = [r for r in runs if r.get('agent') == name][:20]

    posts = db.get_posts(analyst=name, limit=10)
    for post in posts:
        for field in ('tags', 'source_urls', 'facts', 'inferences'):
            val = post.get(field)
            if isinstance(val, str):
                try: post[field] = json.loads(val)
                except: post[field] = []

    # Compute success rate
    total_runs  = len(agent_runs)
    success_runs = sum(1 for r in agent_runs if r.get('status') == 'success')
    total_items  = sum(r.get('items_found', 0) for r in agent_runs)
    total_posted = sum(r.get('items_posted', 0) for r in agent_runs)

    return jsonify({
        'agent': name,
        'display_name': getattr(agent, 'display_name', name),
        'personality': getattr(agent, 'personality', ''),
        'domain_context': getattr(agent, 'domain_context', ''),
        'interval_minutes': AGENT_INTERVALS.get(name, 60),
        'meta': {
            'total_runs': total_runs,
            'success_rate': round(success_runs / total_runs, 3) if total_runs else None,
            'total_items_fetched': total_items,
            'total_posts_saved': total_posted,
            'efficiency_rate': round(total_posted / total_items, 3) if total_items else None,
        },
        'recent_runs': agent_runs,
        'recent_posts': posts,
    })


# ── SSE live feed ─────────────────────────────────────────────────────────────

@app.route('/api/stream')
def sse_stream():
    """
    Server-Sent Events endpoint. Clients connect here to receive real-time
    agent run notifications and stats updates without polling.

    Usage:
        const es = new EventSource('/api/stream');
        es.addEventListener('agent_run', e => console.log(JSON.parse(e.data)));
        es.addEventListener('stats_update', e => console.log(JSON.parse(e.data)));
    """
    if len(_sse_subscribers) >= _SSE_MAX_SUBSCRIBERS:
        return jsonify({'error': 'Too many SSE subscribers'}), 503

    def event_stream():
        q = queue.Queue(maxsize=100)
        with _sse_lock:
            _sse_subscribers.append(q)
        try:
            # Send initial heartbeat
            yield "event: connected\ndata: {\"status\": \"connected\"}\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    # Keepalive ping every 30s to prevent proxy timeout
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_subscribers:
                    _sse_subscribers.remove(q)

    return app.response_class(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
            'Access-Control-Allow-Origin': '*',
        }
    )
