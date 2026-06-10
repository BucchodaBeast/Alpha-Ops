# Alpha Ops — System Architecture

> **Frontier Intelligence Platform**  
> Cross-domain signal detection and intelligence synthesis for Emerging Markets and Frontier Capital.

---

## 1. System Overview

Alpha Ops is a **multi-agent pipeline architecture** that continuously ingests raw data from 14 independent specialist agents, processes it through three enrichment layers, and synthesises finished intelligence products (NEXUS Briefs) for human decision-makers in frontier finance, supply chain, and commodities.

The key architectural insight is **convergence-as-signal**: a single analyst flagging a topic is noise; three independent analysts independently flagging the same entity is a meaningful signal. The system is designed to detect that convergence automatically.

---

## 2. Four-Layer Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — THE WIRE (Signal Ingestion)                                  │
│                                                                         │
│  14 specialist agents run on staggered intervals (15–90 min)            │
│  Each fetches domain-specific data from public APIs + RSS feeds         │
│  Groq LLM (Llama-3.3-70B) structures raw data → typed intelligence     │
│                                                                         │
│  STONE  VOSS  MARA  REED  ATLAS  WATT  TIDE  ECHO                       │
│  LEX    FINN  CARGO TERRA DELPHI GHOST                                  │
│         ↓           ↓           ↓           ↓                           │
│         Posts saved to database with: type, body, facts,                │
│         inferences, confidence (source-capped), tags, source_urls       │
└────────────────────────┬────────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────────────┐
│  LAYER 2 — THE GRID (Entity Extraction + Corroboration)                 │
│                                                                         │
│  Runs every 15 min. Processes last 8h of posts.                         │
│  LLM extracts structured entities: countries, regions, sectors,         │
│  asset_classes, commodities, companies, event_types, severity           │
│                                                                         │
│  Cross-analyst corroboration scoring:                                   │
│  score = analyst_count × entity_weight × avg_confidence × severity_adj │
│                                                                         │
│  Outputs: entity clusters with 2+ independent analysts                  │
│  (single-analyst mentions are discarded as unconfirmed)                 │
└────────────────────────┬────────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────────────┐
│  LAYER 3 — PRESSURE MAP (Magnitude Scoring)                             │
│                                                                         │
│  Runs every 20 min. Consumes Grid clusters.                             │
│  Aggregates by geography (country/region) and scores:                   │
│                                                                         │
│  pressure = avg_corroboration                                           │
│           × domain_diversity    (how many different domains flagging)   │
│           × velocity            (how fast signals are accumulating)     │
│           × compound_risk       (co-occurring high-risk event pairs)    │
│           × severity_multiplier                                         │
│                                                                         │
│  Heat levels: MONITORING < ELEVATED < HIGH < CRITICAL                   │
│  Compound risk pairs: e.g. conflict + supply disruption → ×1.5          │
└────────────────────────┬────────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────────────┐
│  LAYER 4 — THE DESK (NEXUS Brief Synthesis)                             │
│                                                                         │
│  Runs every 25 min. Reads all three prior layers.                       │
│  Triggers when: 3+ analysts converge on same entity,                    │
│  avg confidence ≥ 0.35, topic not seen in last 2h (deduplication TTL)   │
│                                                                         │
│  LLM synthesises: title, synthesis (4-6 sentences), so_what,           │
│  who_affected, timeline, historical_precedent, next_steps,             │
│  what_to_watch, confidence_tier, convergence_score                      │
│                                                                         │
│  Output: NEXUS Brief — finished professional intelligence product        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Confidence Architecture

A key design decision is **source-gated confidence capping**. The system prevents the LLM from expressing false certainty when evidence is thin:

| Sources | Max Confidence | Rationale |
|---------|---------------|-----------|
| 0 | 20% | No corroboration — pure model inference |
| 1 | 45% | Single source — could be mistaken |
| 2 | 65% | Two independent sources — probable |
| 3 | 80% | Three independent sources — likely confirmed |
| 4+ | 90% | Strong multi-source — high confidence |

NEXUS Brief confidence tiers map to:

| Tier | Confidence | Analyst Count |
|------|-----------|---------------|
| EARLY WARNING | 0–40% | 2+ |
| DEVELOPING | 40–60% | 2–3 |
| CONFIRMED | 60–80% | 3+ |
| HIGH CONFIDENCE | 80%+ | 4+ |

---

## 4. Component Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  CLIENT LAYER                                                        │
│                                                                      │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐      │
│  │  Operations     │  │  SSE EventSource                     │      │
│  │  Terminal UI    │  │  (real-time agent run notifications) │      │
│  │  (index.html)   │  │  GET /api/stream                     │      │
│  └────────┬────────┘  └──────────────────┬───────────────────┘      │
└───────────┼──────────────────────────────┼──────────────────────────┘
            │ REST                         │ SSE
┌───────────▼──────────────────────────────▼──────────────────────────┐
│  API LAYER  (Flask + Gunicorn)                                       │
│                                                                      │
│  Public endpoints:                                                   │
│  GET  /api/health           System status                            │
│  GET  /api/posts            Intelligence feed (paginated)            │
│  GET  /api/briefs           NEXUS Briefs                             │
│  GET  /api/stats            Analyst activity                         │
│  GET  /api/agents           Agent metadata                           │
│  GET  /api/grid             Entity clusters                          │
│  GET  /api/pressure         Pressure zones                           │
│  GET  /api/retro/summary    Accuracy / hit rate summary              │
│  GET  /api/stream           SSE live event stream                    │
│                                                                      │
│  Auth endpoints (JWT):                                               │
│  POST /api/auth/register    Create account                           │
│  POST /api/auth/login       Get JWT token                            │
│  GET  /api/auth/me          Authenticated user info                  │
│  GET  /api/watchlist        User's watchlist                         │
│  PUT  /api/watchlist        Update countries/sectors/analysts        │
│  GET  /api/watchlist/feed   Filtered intelligence for this user      │
│                                                                      │
│  Admin endpoints (X-Admin-Key header):                               │
│  POST /api/trigger/{name}   Trigger specific agent                   │
│  POST /api/trigger/all      Trigger all agents                       │
│  GET  /api/runs             Agent run history                        │
│  GET  /api/agents/{n}/trace Observability trace for agent            │
│  POST /api/retro/outcomes   Record SITREP outcome                    │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  PROCESSING LAYER                                                    │
│                                                                      │
│  APScheduler (BackgroundScheduler)                                   │
│  ├── 14 analyst agents (staggered 20–90 min intervals)              │
│  ├── GRID processor (every 15 min)                                  │
│  └── PRESSURE processor (every 20 min)                              │
│      └── DESK synthesiser (every 25 min)                            │
│                                                                      │
│  Thread safety: _scheduler_lock (threading.Lock)                    │
│  Max 1 concurrent instance per agent (max_instances=1)              │
│  SSE broadcast: _publish_event() after each agent run               │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  DATA LAYER                                                          │
│                                                                      │
│  Dual-mode: SQLite (dev/local) ←→ Supabase PostgreSQL (production)  │
│  Runtime detection via SUPABASE_URL env var                          │
│                                                                      │
│  Tables:                                                             │
│  posts           — analyst intelligence signals                      │
│  briefs          — NEXUS Brief convergence products                  │
│  seen_items      — SHA-256 deduplication hashes per agent            │
│  agent_runs      — observability log (status, counts, errors)        │
│  grid_clusters   — entity corroboration clusters (rolling 12h)       │
│  pressure_zones  — geographic pressure scores (replaced each run)    │
│  brief_outcomes  — retrospective scoring (validated/invalidated)     │
│  users           — user accounts (PBKDF2-hashed passwords)           │
│  watchlists      — per-user country/sector/analyst filters           │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 5. LLM Integration Architecture

All LLM calls flow through `agents/base.py:_call_groq()`:

```
Input data → domain_context + data_payload
      ↓
Groq API (Llama-3.3-70B, temperature=0.15)
      ↓
Structured JSON response
      ↓
Validation:
  - source_urls: only URLs present in input data (hallucination guard)
  - confidence: clamped by source_count
  - body + facts: must be non-empty (empty response discarded)
      ↓
Post stored to database
```

**Rate limit management** (Groq free tier = 1,440 req/day):
- Agents staggered with per-agent start delays (0–30 min)
- Max 5 items processed per agent run
- GRID caps at 40 posts per run, 0.3s sleep between calls
- Total estimated: ~900–1,100 LLM calls/day at typical activity
- Exponential backoff on 429 (3 attempts, 12/24/36s waits)

---

## 6. Retrospective Accuracy System

The retrospective scoring system (`retro.py`) closes the feedback loop that transforms Alpha Ops from a generator into a **measurable intelligence system**.

```
NEXUS Brief generated
      ↓
brief_outcomes row created (outcome='pending')
      ↓
Analyst reviews event outcome (24h–30 days later)
      ↓
POST /api/retro/outcomes  {brief_id, outcome, notes, confidence_tier}
      ↓
outcome ∈ {validated, invalidated, partial}
      ↓
hit_rate = (validated + partial×0.5) / (validated + invalidated + partial)
      ↓
Broken down by confidence tier → calibration analysis
(Do CONFIRMED briefs actually hit at 80%+? Do EARLY WARNINGs perform at 40%?)
```

**Why this matters for system credibility**: A system with no feedback mechanism cannot claim predictive validity. The retrospective scorer enables:
1. Calibration analysis (are confidence tiers well-calibrated?)
2. Agent performance attribution (which analysts' signals contribute to validated briefs?)
3. Domain-specific accuracy (is GHOST+CARGO convergence more reliable than STONE+ECHO?)

---

## 7. Authentication & Personalisation

```
POST /api/auth/register → {token, user}
POST /api/auth/login    → {token, user}
      ↓
JWT (HS256, 7-day expiry, PBKDF2-HMAC-SHA256 passwords)
      ↓
PUT /api/watchlist {countries: [...], sectors: [...], analysts: [...]}
      ↓
GET /api/watchlist/feed → posts filtered to user's focus geography/sector
```

Watchlist filtering matches against post tags (entity-extracted by GRID), enabling users to configure a personalised intelligence stream without storing per-user copies of data.

---

## 8. Real-Time Delivery (SSE)

```
Client: const es = new EventSource('/api/stream')

Server:
  - Maintains subscriber queue list (max 50 connections)
  - _publish_event() called after every agent run
  - Events: agent_run, stats_update
  - Keepalive ping every 30s (prevents proxy timeout)
  - Dead subscribers pruned automatically on next broadcast
```

SSE was chosen over WebSocket because:
- Read-only from client perspective (agents write, users read)
- Simpler infrastructure (no WebSocket upgrade, works through most proxies)
- Native browser support, no library required
- Automatic reconnection built into the EventSource spec

---

## 9. Data Flow Diagram

```
External APIs                 Alpha Ops                    Users
─────────────────────────────────────────────────────────────────

Kraken, Yahoo Finance    →  STONE (20min)  ──┐
Reuters RSS, ACLED       →  GHOST (40min)  ──┤  posts table
GDELT, ReliefWeb RSS     →  ATLAS (30min)  ──┤
WHO alerts, ProMED       →  MARA (45min)   ──┤
Shipping AIS RSS         →  TIDE (50min)   ──┤  ← 14 agents
EIA, Ember RSS           →  WATT (60min)   ──┤
Social RSS / GDELT       →  ECHO (40min)   ──┤
FRED, SEC RSS            →  LEX (55min)    ──┘
[+ 6 more agents]           [...]
                                │
                                ▼
                        GRID (15min)        →  grid_clusters table
                        (entity extraction)
                                │
                                ▼
                        PRESSURE (20min)    →  pressure_zones table
                        (magnitude scoring)
                                │
                                ▼
                        DESK (25min)        →  briefs table
                        (NEXUS synthesis)
                                │
                         ┌──────┴───────┐
                         ▼             ▼
                    REST API      SSE stream    →  Ops Terminal UI
                    /api/*        /api/stream   →  User watchlist feed
                                                →  Admin trace
                                                →  Retro scoring
```

---

## 10. Security Architecture

| Concern | Mechanism |
|---------|-----------|
| Admin endpoint protection | `X-Admin-Key` header, compared with `ADMIN_API_KEY` env var |
| User authentication | JWT (HS256), signed with `JWT_SECRET` env var |
| Password storage | PBKDF2-HMAC-SHA256, 260,000 iterations, random salt, constant-time comparison |
| LLM hallucination | URL validation (only input URLs accepted), facts/inferences explicitly separated |
| Source injection | `source_urls` cross-checked against actual input data before storage |
| CORS | Explicit allowlist via `FRONTEND_URL` env var + localhost dev origins |
| SQLite concurrency | WAL mode + connection-per-request pattern |
| Rate limiting | APScheduler `max_instances=1` per agent prevents thundering herd |

---

## 11. Scalability Notes

The current architecture is designed for **single-server deployment** on Render's free/starter tier. Key constraints and their implications:

- **SQLite → Supabase**: Automated dual-mode switching. SQLite is adequate for development and low-traffic production; Supabase (PostgreSQL) handles concurrent write load from multiple agents.
- **APScheduler**: Background thread scheduler — works on single-server deployments. For multi-server scale, replace with a distributed task queue (Celery + Redis or Render's cron jobs).
- **SSE subscribers**: Capped at 50 to prevent memory exhaustion. For higher scale, move to a Redis pub/sub backend.
- **Groq free tier**: ~1,100 LLM calls/day budget. Paid tier removes this constraint entirely.

---

## 12. Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Web framework | Flask 3.x | Lightweight, sufficient for API-only backend |
| Task scheduling | APScheduler 3.x | Simple in-process scheduling, no Redis required |
| LLM provider | Groq (Llama-3.3-70B) | Free tier, fast inference, JSON mode |
| Primary DB | SQLite (dev) / Supabase PostgreSQL (prod) | Zero-config dev, production-grade prod |
| HTTP client | httpx | Async-capable, clean API |
| Feed parsing | feedparser | RSS/Atom ingestion across all agents |
| Authentication | Custom JWT (HS256) + PBKDF2 | No external auth service dependency |
| Deployment | Render (gunicorn, 1 worker, 4 threads) | Free tier compatible |
| Frontend | Vanilla HTML/JS/CSS | No build step, works on GitHub Pages |

---

*Architecture document — Alpha Ops v2.0*
