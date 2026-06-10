import os
from functools import lru_cache

import httpx

OPENDOTA_BASE = "https://api.opendota.com/api"
CDN_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes"

RANK_LABELS = {
    "1": "Herald",
    "2": "Guardian",
    "3": "Crusader",
    "4": "Archon",
    "5": "Legend",
    "6": "Ancient",
    "7": "Divine",
    "8": "Immortal",
}

MIN_GAMES = 200

# Maps UI role labels → OpenDota role tags a hero must have at least one of
ROLE_TAGS: dict[str, list[str]] = {
    "Carry": ["Carry"],
    "Mid": ["Nuker", "Escape"],
    "Offlane": ["Initiator", "Durable", "Disabler"],
    "Soft Support": ["Support", "Disabler"],
    "Hard Support": ["Support"],
}

# In-process cache for matchup data — populated lazily, persists for server lifetime
_matchup_cache: dict[int, list[dict]] = {}


def _params() -> dict:
    key = os.getenv("OPENDOTA_API_KEY")
    return {"api_key": key} if key else {}


@lru_cache(maxsize=1)
def _heroes() -> list[dict]:
    r = httpx.get(f"{OPENDOTA_BASE}/heroes", params=_params())
    r.raise_for_status()
    return r.json()


def _find_hero(name: str) -> dict:
    lower = name.lower()
    for h in _heroes():
        if h["localized_name"].lower() == lower:
            return h
    for h in _heroes():
        if lower in h["localized_name"].lower():
            return h
    raise ValueError(f"Hero '{name}' not found — check spelling.")


def hero_image_url(hero_internal_name: str) -> str:
    """hero_internal_name is the npc_dota_hero_* field from the API."""
    short = hero_internal_name.replace("npc_dota_hero_", "")
    return f"{CDN_BASE}/{short}.png"


@lru_cache(maxsize=1)
def fetch_hero_stats() -> dict[int, dict]:
    """All hero stats from /heroStats keyed by hero_id. Cached for process lifetime."""
    r = httpx.get(f"{OPENDOTA_BASE}/heroStats", params=_params())
    r.raise_for_status()
    return {h["id"]: h for h in r.json()}


def fetch_matchups_sync(hero_id: int) -> list[dict]:
    """Sync matchup fetch with process-level cache (shared with async version)."""
    if hero_id in _matchup_cache:
        return _matchup_cache[hero_id]
    r = httpx.get(f"{OPENDOTA_BASE}/heroes/{hero_id}/matchups", params=_params())
    r.raise_for_status()
    data = r.json()
    _matchup_cache[hero_id] = data
    return data


async def fetch_matchups_async(
    hero_id: int, client: httpx.AsyncClient
) -> tuple[int, list[dict]]:
    """Fetch matchup rows for one hero; returns (hero_id, rows). Uses process-level cache."""
    if hero_id in _matchup_cache:
        return hero_id, _matchup_cache[hero_id]
    r = await client.get(f"{OPENDOTA_BASE}/heroes/{hero_id}/matchups", params=_params())
    r.raise_for_status()
    data = r.json()
    _matchup_cache[hero_id] = data
    return hero_id, data


def score_heroes(
    my_pick_ids: list[int],
    enemy_pick_ids: list[int],
    ban_ids: list[int],
    my_role: str,
    rank: int,
) -> list[dict]:
    """Score all candidate heroes for the given draft state. Returns top 10 sorted by score."""
    all_heroes = _heroes()
    hero_stats = fetch_hero_stats()

    matchup_index: dict[int, dict[int, dict]] = {}
    for eid in enemy_pick_ids:
        rows = fetch_matchups_sync(eid)
        matchup_index[eid] = {row["hero_id"]: row for row in rows}

    excluded = set(my_pick_ids) | set(enemy_pick_ids) | set(ban_ids)
    allowed_tags = set(ROLE_TAGS.get(my_role, [])) if my_role else set()
    scored: list[dict] = []

    for h in all_heroes:
        hid = h["id"]
        if hid in excluded:
            continue

        candidate_roles = h.get("roles", [])
        if allowed_tags and not (allowed_tags & set(candidate_roles)):
            continue

        s = hero_stats.get(hid, {})
        picks = s.get(f"{rank}_pick", 0)
        wins = s.get(f"{rank}_win", 0)
        base = (wins / picks - 0.50) if picks > 0 else 0.0

        advantages = []
        for eid in enemy_pick_ids:
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
