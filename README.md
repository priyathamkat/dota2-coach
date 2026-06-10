# Dota 2 Draft Coach

A real-time All-Pick draft assistant powered by [OpenDota](https://www.opendota.com/) data and Claude.

## Features

- **Live recommendations** — hero suggestions scored by counter-pick strength and win rate at your rank bracket
- **Role filter** — hard-filters candidates to heroes that actually play your role (Carry, Mid, Offlane, Soft Support, Hard Support)
- **Top 3 analysis** — Claude explains why each recommended pick is strong in the specific draft context
- **Ask Coach** — free-form chat with a LangGraph agent that has access to live matchup and win rate data
- **Draft-aware chat** — the agent always sees the current draft state (your picks, enemy picks, bans, role, faction, rank) when you ask a question

## Architecture

```
ui.html              Alpine.js + Tailwind single-page frontend (no build step)
dota2_coach/
  app.py             FastAPI server — /api/heroes, /api/recommend, /api/explain, /api/chat
  agent.py           LangGraph ReAct agent (langchain.agents.create_agent)
  opendota.py        OpenDota API helpers, shared scoring logic, caches
```

**Recommendation scoring** (`/api/recommend`): fetches matchup data for all known enemy picks in parallel, then scores every eligible hero as `0.6 × counter_score + 0.4 × base_win_rate_advantage`. Heroes that don't match the selected role are excluded entirely.

**Agent tools**: `get_hero_winrates`, `get_hero_matchups`, `get_draft_recommendations` — the agent decides which to call based on the question.

## Setup

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
git clone <repo>
cd dota2-coach
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and optionally OPENDOTA_API_KEY in .env
uv sync
```

An `OPENDOTA_API_KEY` is optional but recommended to avoid rate limits on the free tier.

## Running

```bash
uv run uvicorn dota2_coach.app:app --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

## Development

```bash
uv sync --group dev   # installs ruff and ty

uv run ruff check dota2_coach/
uv run ruff format dota2_coach/
uv run ty check dota2_coach/
```
