import asyncio
from pathlib import Path

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from dota2_coach.opendota import (
    RANK_LABELS, _heroes, fetch_hero_stats, fetch_matchups_async, hero_image_url,
)

load_dotenv()

app = FastAPI()
anthropic_client = Anthropic()

UI_HTML = Path(__file__).parent.parent / "ui.html"

MIN_GAMES = 200
MODEL = "claude-sonnet-4-6"

# Maps UI role labels → OpenDota role tags a hero must have at least one of
ROLE_TAGS: dict[str, list[str]] = {
    "Carry":        ["Carry"],
    "Mid":          ["Nuker", "Escape"],
    "Offlane":      ["Initiator", "Durable", "Disabler"],
    "Soft Support": ["Support", "Disabler"],
    "Hard Support": ["Support"],
}


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
    return FileResponse(UI_HTML)


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

    excluded     = set(req.my_picks) | set(req.enemy_picks) | set(req.bans)
    allowed_tags = set(ROLE_TAGS.get(req.my_role, [])) if req.my_role else set()
    scored       = []

    for h in heroes:
        hid = h["id"]
        if hid in excluded:
            continue

        candidate_roles = h.get("roles", [])

        # Hard role filter: skip heroes that don't match the selected role
        if allowed_tags and not (allowed_tags & set(candidate_roles)):
            continue

        # base_score: win rate advantage over 50% at the selected rank
        s     = hero_stats.get(hid, {})
        picks = s.get(f"{req.rank}_pick", 0)
        wins  = s.get(f"{req.rank}_win", 0)
        base  = (wins / picks - 0.50) if picks > 0 else 0.0

        # counter_score: avg winrate advantage vs known enemy picks
        advantages = []
        for eid in req.enemy_picks:
            row = matchup_index.get(eid, {}).get(hid)
            if row and row["games_played"] >= MIN_GAMES:
                advantages.append(0.5 - row["wins"] / row["games_played"])
        counter = sum(advantages) / len(advantages) if advantages else 0.0

        final = 0.6 * counter + 0.4 * base

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
# POST /api/explain  — direct Claude call, no tool loop
# ---------------------------------------------------------------------------

class ExplainRequest(BaseModel):
    my_picks:    list[int] = []
    enemy_picks: list[int] = []
    bans:        list[int] = []
    my_role:     str = ""
    my_faction:  str = "radiant"
    rank:        int = 5
    top_heroes:  list[dict] = []


def _build_explain_prompt(req: ExplainRequest) -> str:
    hero_names = {h["id"]: h["localized_name"] for h in _heroes()}
    rank_label = RANK_LABELS.get(str(req.rank), "Legend")

    context_lines = [
        f"Faction: {req.my_faction.title()} | Role: {req.my_role or 'Any'} | Rank: {rank_label}",
    ]
    if req.my_picks:
        context_lines.append("My team: " + ", ".join(hero_names.get(i, str(i)) for i in req.my_picks))
    if req.enemy_picks:
        context_lines.append("Enemy: " + ", ".join(hero_names.get(i, str(i)) for i in req.enemy_picks))
    if req.bans:
        context_lines.append("Banned: " + ", ".join(hero_names.get(i, str(i)) for i in req.bans))

    hero_lines = "\n".join(
        f"{i+1}. {h['name']}  (counter {h['counter_score']:+.3f}, base WR {h['base_score']:+.3f})"
        for i, h in enumerate(req.top_heroes[:3])
    )

    return f"""You are a concise Dota 2 draft coach. Draft context:
{chr(10).join(context_lines)}

Top 3 algorithmically scored picks:
{hero_lines}

Write exactly 3 lines — one per hero — using this format:
[Hero Name]: [one sentence, ≤15 words, why it's strong in this specific draft]

Be concrete: mention specific enemy heroes countered, win-rate strength, or synergy with team picks. No intro or filler."""


@app.post("/api/explain")
async def explain(req: ExplainRequest):
    if not req.top_heroes:
        return {"explanation": ""}

    prompt = _build_explain_prompt(req)

    def _call():
        msg = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    text = await run_in_threadpool(_call)
    return {"explanation": text}


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    from dota2_coach.agent import chat
    response = await run_in_threadpool(chat, req.message)
    return {"response": response}
