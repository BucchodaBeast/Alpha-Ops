"""
app.py — Alpha Ops Intelligence Platform
Flask backend + APScheduler with staggered agent intervals
"""

import os
import json
import logging
import threading
import queue
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(32).hex())

FRONTEND_URL = os.getenv('FRONTEND_URL', '')
allowed_origins = ['http://localhost:3000', 'http://127.0.0.1:5000']
if FRONTEND_URL:
    allowed_origins.append(FRONTEND_URL)
CORS(app, origins=allowed_origins, supports_credentials=False)

ADMIN_API_KEY = os.getenv('ADMIN_API_KEY', '')

# ── Agent imports ──────────────────────────────────────────────────────────────
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
        agents['WATT']  = WattAgent()
        agents['TIDE']  = TideAgent()
        agents['ECHO']  = EchoAgent()
        agents['LEX']   = LexAgent()
    except Exception as e:
        logger.error(f"Failed to load ATLAS/WATT/TIDE/ECHO/LEX: {e}")
    try:
        from agents.finn_cargo_terra_delphi_ghost import (
            FinnAgent, CargoAgent, TerraAgent, DelphiAgent, GhostAgent
        )
        agents['FINN']   = FinnAgent()
        agents['CARGO']  = CargoAgent()
        agents['TERRA']  = TerraAgent()
        agents['DELPHI'] = DelphiAgent()
        agents['GHOST']  = GhostAgent()
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

# ── Database ───────────────────────────────────────────────────────────────────
from database import Database
db = Database()

# ── Auth decorator ─────────────────────────────────────────────────────────────
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

# ── SSE Event Bus ──────────────────────────────────────────────────────────────
_sse_subscribers: list[queue.Queue] = []
_sse_lock = threading.Lock()
_SSE_MAX_SUBSCRIBERS = 10

def _publish_event(event_type: str, data: dict):
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)

# ── Scheduler ──────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(daemon=True)

def _run_agent(name: str):
    agent = AGENTS.get(name)
    if not agent:
        return
    try:
        count = agent.run()
        logger.info(f"[SCHEDULER] {name} → {count} posts")
        _publish_event('agent_run', {
            'agent': name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error(f"[SCHEDULER] {name} failed: {e}")

AGENT_INTERVALS = {
    'STONE':    30,
    'GHOST':    50,
    'ATLAS':    40,
    'MARA':     55,
    'TIDE':     60,
    'ECHO':     50,
    'VOSS':     45,
    'TERRA':    90,
    'WATT':     70,
    'LEX':      65,
    'CARGO':    75,
    'FINN':     85,
    'REED':     120,
    'DELPHI':   100,
    'DESK':     35,
    'GRID':     25,
    'PRESSURE': 30,
}

# Agents fire one at a time — 3 min apart so server never spikes
START_DELAYS = {
    'STONE':    5,
    'ATLAS':    8,
    'VOSS':     11,
    'ECHO':     14,
    'GHOST':    17,
    'MARA':     20,
    'GRID':     23,
    'WATT':     26,
    'TIDE':     29,
    'LEX':      32,
    'CARGO':    35,
    'PRESSURE': 38,
    'TERRA':    41,
    'FINN':     44,
    'DELPHI':   47,
    'REED':     50,
    'DESK':     55,
}

def start_scheduler():
    if scheduler.running:
        return
    for name, interval in AGENT_INTERVALS.items():
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
    logger.info("Scheduler started")

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

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

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
    limit   = min(int(request.args.get('limit', 50)), 200)
    offset  = int(request.args.get('offset', 0))
    posts   = db.get_posts(analyst=analyst, limit=limit, offset=offset)
    for post in posts:
        for field in ('tags', 'source_urls', 'facts', 'inferences'):
            val = post.get(field)
            if isinstance(val, str):
                try: post[field] = json.loads(val)
                except: post[field] = []
    return jsonify({'posts': posts, 'count': len(posts)})

@app.route('/api/briefs')
def get_briefs():
    limit  = min(int(request.args.get('limit', 20)), 100)
    briefs = db.get_briefs(limit=limit)
    for brief in briefs:
        for field in ('analysts_involved', 'contributing_post_ids'):
            val = brief.get(field)
            if isinstance(val, str):
                try: brief[field] = json.loads(val)
                except: brief[field] = []
    return jsonify({'briefs': briefs, 'count': len(briefs)})

@app.route('/api/stats')
def get_stats():
    stats      = db.get_stats()
    agent_meta = {}
    for name, agent in AGENTS.items():
        agent_meta[name] = {
            'display_name':     getattr(agent, 'display_name', name),
            'personality':      getattr(agent, 'personality', '')[:100],
            'interval_minutes': AGENT_INTERVALS.get(name, 60),
        }
    return jsonify({**stats, 'agent_meta': agent_meta})

@app.route('/api/agents')
def get_agents():
    activity    = db.get_stats().get('analyst_activity', {})
    agents_info = []
    for name, agent in AGENTS.items():
        agents_info.append({
            'name':             name,
            'display_name':     getattr(agent, 'display_name', name),
            'personality':      getattr(agent, 'personality', ''),
            'domain_context':   getattr(agent, 'domain_context', '')[:200],
            'interval_minutes': AGENT_INTERVALS.get(name, 60),
            'post_count':       activity.get(name, 0),
        })
    return jsonify({'agents': agents_info})

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

@app.route('/api/runs')
@require_admin
def get_runs():
    runs = db.get_agent_runs(limit=100)
    return jsonify({'runs': runs})

# ── Trigger routes (POST — Hoppscotch / API clients) ──────────────────────────

@app.route('/api/trigger/<agent_name>', methods=['POST'])
@require_admin
def trigger_agent(agent_name: str):
    name  = agent_name.upper()
    agent = AGENTS.get(name)
    if not agent:
        return jsonify({'error': f'Agent {name} not found'}), 404
    t = threading.Thread(target=_run_agent, args=[name], daemon=True)
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

# ── GET trigger routes (browser URL bar — no headers needed) ──────────────────

@app.route('/go/<agent_name>')
def go_trigger(agent_name: str):
    name = agent_name.upper()
    if name == 'ALL':
        triggered = []
        for n in AGENTS:
            t = threading.Thread(target=_run_agent, args=[n], daemon=True)
            t.start()
            triggered.append(n)
        return jsonify({'status': 'triggered', 'agents': triggered})
    agent = AGENTS.get(name)
    if not agent:
        return jsonify({'error': f'Agent {name} not found'}), 404
    t = threading.Thread(target=_run_agent, args=[name], daemon=True)
    t.start()
    return jsonify({'status': 'triggered', 'agent': name})

# ── SSE live feed ──────────────────────────────────────────────────────────────

@app.route('/api/stream')
def sse_stream():
    if len(_sse_subscribers) >= _SSE_MAX_SUBSCRIBERS:
        return jsonify({'error': 'Too many SSE subscribers'}), 503

    def event_stream():
        q = queue.Queue(maxsize=100)
        with _sse_lock:
            _sse_subscribers.append(q)
        try:
            yield 'event: connected\ndata: {"status": "connected"}\n\n'
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ': keepalive\n\n'
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
            'X-Accel-Buffering': 'no',
        }
    )

# ── Agent trace ────────────────────────────────────────────────────────────────

@app.route('/api/agents/<agent_name>/trace')
@require_admin
def agent_trace(agent_name: str):
    name  = agent_name.upper()
    agent = AGENTS.get(name)
    if not agent:
        return jsonify({'error': f'Agent {name} not found'}), 404
    runs        = db.get_agent_runs(limit=100)
    agent_runs  = [r for r in runs if r.get('agent') == name][:20]
    posts       = db.get_posts(analyst=name, limit=10)
    for post in posts:
        for field in ('tags', 'source_urls', 'facts', 'inferences'):
            val = post.get(field)
            if isinstance(val, str):
                try: post[field] = json.loads(val)
                except: post[field] = []
    total_runs   = len(agent_runs)
    success_runs = sum(1 for r in agent_runs if r.get('status') == 'success')
    total_items  = sum(r.get('items_found', 0) for r in agent_runs)
    total_posted = sum(r.get('items_posted', 0) for r in agent_runs)
    return jsonify({
        'agent':        name,
        'display_name': getattr(agent, 'display_name', name),
        'personality':  getattr(agent, 'personality', ''),
        'interval_minutes': AGENT_INTERVALS.get(name, 60),
        'meta': {
            'total_runs':        total_runs,
            'success_rate':      round(success_runs / total_runs, 3) if total_runs else None,
            'total_items_fetched': total_items,
            'total_posts_saved': total_posted,
        },
        'recent_runs':  agent_runs,
        'recent_posts': posts,
    })

# ── Boot ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    start_scheduler()
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    start_scheduler()
