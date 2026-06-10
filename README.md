# Alpha Ops — Frontier Intelligence Platform

> Cross-domain intelligence for Emerging Markets and Frontier Capital.
> Built for frontier fund managers, supply chain directors, and commodity traders.

---

## What It Is

Alpha Ops runs 14 independent intelligence analysts watching different domains simultaneously:
geopolitics, markets, conflict, health, climate, shipping, regulatory, prediction markets.

When 3+ analysts independently flag the same topic, **THE DESK** synthesises their reports
into a full **SITREP** — a professional intelligence brief with investment implications,
affected parties, timeline, and actionable next steps.

This is not a news aggregator. It is a **cross-domain pattern detection system**.

---

## The Analysts

| Name | Domain | Interval |
|------|--------|----------|
| STONE | Markets & EM Currency | 20 min |
| VOSS | Insider Flow & ETF Positioning | 35 min |
| MARA | Health & Epidemic Intelligence | 45 min |
| REED | Research & Technology | 90 min |
| ATLAS | Geopolitics & Political Risk | 30 min |
| WATT | Energy & Infrastructure | 60 min |
| TIDE | Maritime & Trade Routes | 50 min |
| ECHO | Social Sentiment & Narrative | 40 min |
| LEX | Regulatory & Legal | 55 min |
| FINN | Investment Opportunities | 75 min |
| CARGO | Supply Chain Intelligence | 65 min |
| TERRA | Climate & Environmental | 80 min |
| DELPHI | Prediction Markets | 85 min |
| GHOST | Conflict & Instability | 40 min |
| THE DESK | Convergence Synthesis | 25 min |

---

## Structure

```
alphaops/
├── app.py                          # Flask app + scheduler
├── database.py                     # SQLite/Supabase dual layer
├── requirements.txt
├── render.yaml
├── Procfile
├── static/
│   └── index.html                  # Operations terminal UI
└── agents/
    ├── __init__.py
    ├── base.py                     # BaseAgent + Groq LLM caller
    ├── desk.py                     # THE DESK — SITREP synthesis
    ├── stone.py                    # Markets
    ├── voss.py                     # Insider flow
    ├── mara.py                     # Health
    ├── reed.py                     # Research
    ├── atlas_watt_tide_echo_lex.py # Geopolitics, Energy, Maritime, Social, Regulatory
    └── finn_cargo_terra_delphi_ghost.py # Investment, Supply Chain, Climate, Predictions, Conflict
```

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/alpha-ops.git
cd alpha-ops
pip install -r requirements.txt
```

### 2. Environment variables

Create a `.env` file or set in Render dashboard:

```env
# Required
GROQ_API_KEY=your_groq_api_key_here

# Security
SECRET_KEY=generate_a_random_string
ADMIN_API_KEY=your_admin_key_for_trigger_endpoints

# Frontend (your GitHub Pages URL)
FRONTEND_URL=https://YOUR_USERNAME.github.io

# Optional — persistent storage (recommended for production)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_supabase_service_key

# Optional — enhances STONE agent
FRED_API_KEY=your_fred_api_key
```

**Get your free Groq API key:** https://console.groq.com

### 3. Run locally

```bash
python app.py
# Open http://localhost:5000/static/index.html
```

### 4. Deploy to Render

1. Push to GitHub
2. Create new **Web Service** on Render, connect your repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`
5. Add all environment variables in Render dashboard
6. Deploy

### 5. Deploy frontend to GitHub Pages

Copy `static/index.html` to your GitHub Pages repo root.
Set `FRONTEND_URL` in Render to your Pages URL.

---

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/health` | GET | — | System status |
| `/api/posts` | GET | — | Intelligence feed |
| `/api/posts?analyst=STONE` | GET | — | Filter by analyst |
| `/api/briefs` | GET | — | SITREP convergence briefs |
| `/api/stats` | GET | — | Analyst activity stats |
| `/api/agents` | GET | — | Agent metadata |
| `/api/trigger/{NAME}` | POST | Admin | Trigger specific agent |
| `/api/trigger/all` | POST | Admin | Trigger all agents |

**Admin auth:** Include `X-Admin-Key: YOUR_ADMIN_API_KEY` header.

---

## How SITREP Convergence Works

1. Agents run on staggered intervals, each watching their domain
2. Every signal is tagged with topic keywords
3. **THE DESK** runs every 25 minutes, scanning the last 6 hours of signals
4. When 2+ analysts independently tag the same topic → convergence detected
5. When 3+ analysts converge with avg confidence ≥ 0.35 → full SITREP generated
6. SITREP includes: synthesis body, so-what, who's affected, timeline, next steps, what to watch, confidence tier
7. Each topic is debounced (2h TTL) to prevent duplicate briefs

**Confidence Tiers:**
- `EARLY WARNING` — 0–40% confidence, 2 analysts
- `DEVELOPING` — 40–60% confidence, 2–3 analysts  
- `CONFIRMED` — 60–80% confidence, 3+ analysts
- `HIGH CONFIDENCE` — 80%+ confidence, 4+ analysts

---

## Groq Free Tier Management

Agents are staggered to stay within Groq's free tier (1,440 requests/day):
- Fastest interval: 20 min (STONE) → max 72 runs/day
- Each run processes max 5 items → max 360 LLM calls/day for STONE
- All 14 agents combined stay under 1,200 LLM calls/day at typical activity

If you hit rate limits, increase agent intervals in `app.py` → `AGENT_INTERVALS`.

---

## Optional API Keys

| Service | Key | What it enables |
|---------|-----|-----------------|
| FRED | `FRED_API_KEY` | USD trade-weighted index, yield curve data |
| ACLED | `ACLED_API_KEY` | Conflict event data in GHOST agent |
| EIA | `EIA_API_KEY` | Detailed energy price data in WATT agent |

All are free to register. System works without them — these enhance signal quality.

---

## Target Audience

Built for professionals making decisions with money in high-growth unstable markets:
- Frontier and emerging market fund managers
- Supply chain and sourcing directors (fashion, electronics, food)
- Commodity traders (oil, metals, agriculture)
- Development finance institutions and NGOs

---

## Roadmap

- [ ] Personalized watchlists per user (country/sector focus)
- [ ] Email digest of daily SITREPs
- [ ] SITREP historical hit rate tracking (predictive scoring)
- [ ] White-label API for enterprise clients
- [ ] CORS: update `FRONTEND_URL` env var with your specific GitHub Pages URL

---

*Built with Groq (Llama-3.3-70B), Flask, and public intelligence sources.*
