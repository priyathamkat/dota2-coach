import os
from functools import lru_cache

import httpx

OPENDOTA_BASE = "https://api.opendota.com/api"
CDN_BASE = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes"

RANK_LABELS = {
    "1": "Herald", "2": "Guardian", "3": "Crusader",
    "4": "Archon",  "5": "Legend",  "6": "Ancient",
    "7": "Divine",  "8": "Immortal",
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


async def fetch_matchups_async(
    hero_id: int, client: httpx.AsyncClient
) -> tuple[int, list[dict]]:
    """Fetch matchup rows for one hero; returns (hero_id, rows). Uses process-level cache."""
    if hero_id in _matchup_cache:
        return hero_id, _matchup_cache[hero_id]
    r = await client.get(
        f"{OPENDOTA_BASE}/heroes/{hero_id}/matchups", params=_params()
    )
    r.raise_for_status()
    data = r.json()
    _matchup_cache[hero_id] = data
    return hero_id, data
