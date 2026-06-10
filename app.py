import asyncio

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from opendota import _heroes, fetch_hero_stats, fetch_matchups_async, hero_image_url

load_dotenv()

app = FastAPI()

MIN_GAMES = 200


# ---------------------------------------------------------------------------
# Startup — warm caches so first request isn't slow
# ---------------------------------------------------------------------------

@app.on_event("startup")
def warm_cache():
    _heroes()
    fetch_hero_stats()


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse("ui.html")


# ---------------------------------------------------------------------------
# GET /api/heroes
# ---------------------------------------------------------------------------

@app.get("/api/heroes")
def get_heroes():
    return [
        {
            "id":           h["id"],
            "name":         h["localized_name"],
            "internal":     h["name"],
            "primary_attr": h["primary_attr"],
            "attack_type":  h["attack_type"],
            "roles":        h.get("roles", []),
            "image_url":    hero_image_url(h["name"]),
        }
        for h in _heroes()
    ]


# ---------------------------------------------------------------------------
# POST /api/recommend
# ---------------------------------------------------------------------------

class RecommendRequest(BaseModel):
    my_picks:    list[int] = []
    enemy_picks: list[int] = []
    bans:        list[int] = []
    my_role:     str = ""
    rank:        int = 5


@app.post("/api/recommend")
async def recommend(req: RecommendRequest):
    heroes     = _heroes()
    hero_stats = fetch_hero_stats()
    hero_map   = {h["id"]: h for h in heroes}

    # Fetch matchup data for all known enemy picks in parallel
    matchup_index: dict[int, dict[int, dict]] = {}
    if req.enemy_picks:
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[fetch_matchups_async(eid, client) for eid in req.enemy_picks],
                return_exceptions=True,
            )
        for item in results:
            if isinstance(item, Exception):
                continue
            enemy_id, matchup_rows = item
            matchup_index[enemy_id] = {row["hero_id"]: row for row in matchup_rows}

    excluded = set(req.my_picks) | set(req.enemy_picks) | set(req.bans)
    scored   = []

    for h in heroes:
        hid = h["id"]
        if hid in excluded:
            continue

        # base_score: how far above/below 50% this hero wins at the selected rank
        s     = hero_stats.get(hid, {})
        picks = s.get(f"{req.rank}_pick", 0)
        wins  = s.get(f"{req.rank}_win", 0)
        wr    = wins / picks if picks > 0 else 0.50
        base  = wr - 0.50

        # counter_score: average winrate advantage vs known enemy picks
        advantages = []
        for eid in req.enemy_picks:
            row = matchup_index.get(eid, {}).get(hid)
            if row and row["games_played"] >= MIN_GAMES:
                # enemy's win rate *against* this hero — lower means we win more
                advantages.append(0.5 - row["wins"] / row["games_played"])
        counter = sum(advantages) / len(advantages) if advantages else 0.0

        # role_penalty: prefer heroes that fit the desired role
        candidate_roles = h.get("roles", [])
        desired = req.my_role
        if desired and desired not in candidate_roles:
            role_pen = -0.05
        else:
            overlap  = sum(
                1 for pid in req.my_picks
                if desired and desired in (hero_map.get(pid, {}).get("roles") or [])
            )
            role_pen = -0.02 * overlap

        final = 0.50 * counter + 0.35 * base + 0.15 * role_pen

        scored.append({
            "hero_id":       hid,
            "name":          h["localized_name"],
            "image_url":     hero_image_url(h["name"]),
            "roles":         candidate_roles,
            "final_score":   round(final, 4),
            "counter_score": round(counter, 4),
            "base_score":    round(base, 4),
        })

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored[:10]


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    from agent import chat
    response = await run_in_threadpool(chat, req.message)
    return {"response": response}
