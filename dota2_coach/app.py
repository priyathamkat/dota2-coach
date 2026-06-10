import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from dota2_coach.opendota import (
    _heroes,
    fetch_hero_stats,
    fetch_matchups_async,
    hero_image_url,
    ROLE_TAGS,
    MIN_GAMES,
)

load_dotenv()

UI_HTML = Path(__file__).parent.parent / "ui.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    _heroes()
    fetch_hero_stats()
    yield


app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    return FileResponse(UI_HTML)


# ---------------------------------------------------------------------------
# GET /api/heroes
# ---------------------------------------------------------------------------


@app.get("/api/heroes")
def get_heroes():
    return [
        {
            "id": h["id"],
            "name": h["localized_name"],
            "internal": h["name"],
            "primary_attr": h["primary_attr"],
            "attack_type": h["attack_type"],
            "roles": h.get("roles", []),
            "image_url": hero_image_url(h["name"]),
        }
        for h in _heroes()
    ]


# ---------------------------------------------------------------------------
# POST /api/recommend  — fast async path with parallel matchup fetching
# ---------------------------------------------------------------------------


class RecommendRequest(BaseModel):
    my_picks: list[int] = []
    enemy_picks: list[int] = []
    bans: list[int] = []
    my_role: str = ""
    rank: int = 5


@app.post("/api/recommend")
async def recommend(req: RecommendRequest):
    heroes = _heroes()
    hero_stats = fetch_hero_stats()

    matchup_index: dict[int, dict[int, dict]] = {}
    if req.enemy_picks:
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *[fetch_matchups_async(eid, client) for eid in req.enemy_picks],
                return_exceptions=True,
            )
        for item in results:
            if isinstance(item, BaseException):
                continue
            enemy_id, matchup_rows = item
            matchup_index[enemy_id] = {row["hero_id"]: row for row in matchup_rows}

    excluded = set(req.my_picks) | set(req.enemy_picks) | set(req.bans)
    allowed_tags = set(ROLE_TAGS.get(req.my_role, [])) if req.my_role else set()
    scored = []

    for h in heroes:
        hid = h["id"]
        if hid in excluded:
            continue

        candidate_roles = h.get("roles", [])
        if allowed_tags and not (allowed_tags & set(candidate_roles)):
            continue

        s = hero_stats.get(hid, {})
        picks = s.get(f"{req.rank}_pick", 0)
        wins = s.get(f"{req.rank}_win", 0)
        base = (wins / picks - 0.50) if picks > 0 else 0.0

        advantages = []
        for eid in req.enemy_picks:
            row = matchup_index.get(eid, {}).get(hid)
            if row and row["games_played"] >= MIN_GAMES:
                advantages.append(0.5 - row["wins"] / row["games_played"])
        counter = sum(advantages) / len(advantages) if advantages else 0.0

        final = 0.6 * counter + 0.4 * base

        scored.append(
            {
                "hero_id": hid,
                "name": h["localized_name"],
                "image_url": hero_image_url(h["name"]),
                "roles": candidate_roles,
                "final_score": round(final, 4),
                "counter_score": round(counter, 4),
                "base_score": round(base, 4),
            }
        )

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored[:10]


# ---------------------------------------------------------------------------
# POST /api/explain  — routed through the LangGraph agent
# ---------------------------------------------------------------------------


class ExplainRequest(BaseModel):
    my_picks: list[int] = []
    enemy_picks: list[int] = []
    bans: list[int] = []
    my_role: str = ""
    my_faction: str = "radiant"
    rank: int = 5
    top_heroes: list[dict] = []


@app.post("/api/explain")
async def explain(req: ExplainRequest):
    if not req.top_heroes:
        return {"explanation": ""}

    from dota2_coach.agent import explain_draft

    draft_context = {
        "my_faction": req.my_faction,
        "my_role": req.my_role,
        "rank": req.rank,
        "my_picks": req.my_picks,
        "enemy_picks": req.enemy_picks,
        "bans": req.bans,
    }
    text = await run_in_threadpool(explain_draft, req.top_heroes, draft_context)
    return {"explanation": text}


# ---------------------------------------------------------------------------
# POST /api/chat  — routed through the LangGraph agent with draft context
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    my_picks: list[int] = []
    enemy_picks: list[int] = []
    bans: list[int] = []
    my_role: str = ""
    my_faction: str = "radiant"
    rank: int = 5


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    from dota2_coach.agent import chat

    draft_context = (
        {
            "my_faction": req.my_faction,
            "my_role": req.my_role,
            "rank": req.rank,
            "my_picks": req.my_picks,
            "enemy_picks": req.enemy_picks,
            "bans": req.bans,
        }
        if any([req.my_picks, req.enemy_picks, req.bans, req.my_role])
        else None
    )

    response = await run_in_threadpool(chat, req.message, draft_context)
    return {"response": response}
