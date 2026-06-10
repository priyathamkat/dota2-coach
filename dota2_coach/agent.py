import httpx
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain.agents import create_agent

from dota2_coach.opendota import (
    OPENDOTA_BASE,
    RANK_LABELS,
    MIN_GAMES,
    _params,
    _heroes,
    _find_hero,
    fetch_hero_stats,
    score_heroes,
)

load_dotenv()

MODEL = "claude-sonnet-4-6"
_BASE_SYSTEM_PROMPT = (
    "You are an expert Dota 2 coach. Help the user improve their gameplay with "
    "data-driven advice. When analyzing a draft, be concise and specific — mention "
    "the exact enemy heroes being countered or synergies with allied picks."
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def get_hero_winrates(hero_name: str) -> str:
    """Get win rates for a Dota 2 hero broken down by rank bracket."""
    hero = _find_hero(hero_name)
    stats = fetch_hero_stats()

    h = stats.get(hero["id"])
    if not h:
        return f"No stats found for {hero['localized_name']}."

    lines = [f"Win rates for {hero['localized_name']}:"]
    for rank_num, label in RANK_LABELS.items():
        picks = h.get(f"{rank_num}_pick", 0)
        wins = h.get(f"{rank_num}_win", 0)
        if picks > 0:
            lines.append(f"  {label}: {wins / picks * 100:.1f}%  ({picks:,} picks)")

    pro_picks = h.get("pro_pick", 0)
    pro_wins = h.get("pro_win", 0)
    if pro_picks > 0:
        lines.append(f"  Pro: {pro_wins / pro_picks * 100:.1f}%  ({pro_picks} picks)")

    return "\n".join(lines)


@tool
def get_hero_matchups(hero_name: str) -> str:
    """Get matchup data for a hero — which heroes it counters and which counter it."""
    hero = _find_hero(hero_name)

    r = httpx.get(f"{OPENDOTA_BASE}/heroes/{hero['id']}/matchups", params=_params())
    r.raise_for_status()
    matchups = r.json()

    hero_names = {h["id"]: h["localized_name"] for h in _heroes()}

    scored = [
        {**m, "winrate": m["wins"] / m["games_played"]}
        for m in matchups
        if m["games_played"] >= MIN_GAMES
    ]
    scored.sort(key=lambda m: m["winrate"])

    def fmt(entries: list[dict]) -> list[str]:
        return [
            f"  {hero_names.get(m['hero_id'], m['hero_id'])}: "
            f"{m['winrate'] * 100:.1f}% ({m['games_played']:,} games)"
            for m in entries
        ]

    lines = [
        f"Matchups for {hero['localized_name']}:",
        "",
        f"{hero['localized_name']} counters (best winrate against):",
        *fmt(scored[-5:][::-1]),
        "",
        "Countered by (worst winrate against):",
        *fmt(scored[:5]),
    ]
    return "\n".join(lines)


@tool
def get_draft_recommendations(
    enemy_picks: str = "",
    my_role: str = "",
    rank: int = 5,
    my_picks: str = "",
    bans: str = "",
) -> str:
    """
    Get ranked hero recommendations for the current All-Pick draft.

    Args:
        enemy_picks: comma-separated enemy hero names, e.g. "Invoker, Phantom Assassin"
        my_role: your role — one of: Carry, Mid, Offlane, Soft Support, Hard Support
        rank: bracket 1-8 (1=Herald, 5=Legend, 8=Immortal); default 5
        my_picks: comma-separated hero names already on your team
        bans: comma-separated banned hero names
    """

    def _resolve(names_str: str) -> list[int]:
        ids = []
        for name in names_str.split(","):
            name = name.strip()
            if not name:
                continue
            try:
                ids.append(_find_hero(name)["id"])
            except ValueError:
                pass
        return ids

    results = score_heroes(
        my_pick_ids=_resolve(my_picks),
        enemy_pick_ids=_resolve(enemy_picks),
        ban_ids=_resolve(bans),
        my_role=my_role,
        rank=rank,
    )

    if not results:
        return "No recommendations found for the given criteria."

    rank_label = RANK_LABELS.get(str(rank), str(rank))
    lines = [f"Top recommendations (role: {my_role or 'any'}, rank: {rank_label}):"]
    for i, h in enumerate(results, 1):
        roles_str = ", ".join(h["roles"][:2])
        lines.append(
            f"{i}. {h['name']} [{roles_str}] — "
            f"score: {h['final_score']:+.3f} "
            f"(counter: {h['counter_score']:+.3f}, base WR: {h['base_score']:+.3f})"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent graph
# ---------------------------------------------------------------------------

tools = [get_hero_winrates, get_hero_matchups, get_draft_recommendations]
llm = ChatAnthropic(model_name=MODEL, thinking={"type": "adaptive"})  # type: ignore[call-arg]
graph = create_agent(llm, tools=tools)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _draft_context_block(draft_context: dict) -> str:
    """Format a draft context dict as a readable block for the system prompt."""
    hero_names = {h["id"]: h["localized_name"] for h in _heroes()}
    rank_label = RANK_LABELS.get(str(draft_context.get("rank", 5)), "Legend")

    lines = [
        "--- Current Draft State ---",
        f"Faction: {draft_context.get('my_faction', 'radiant').title()}",
        f"Role: {draft_context.get('my_role') or 'not specified'}",
        f"Rank: {rank_label}",
    ]

    my_picks = draft_context.get("my_picks", [])
    if my_picks:
        lines.append(
            "My team: " + ", ".join(hero_names.get(i, str(i)) for i in my_picks)
        )

    enemy_picks = draft_context.get("enemy_picks", [])
    if enemy_picks:
        lines.append(
            "Enemy picks: " + ", ".join(hero_names.get(i, str(i)) for i in enemy_picks)
        )

    bans = draft_context.get("bans", [])
    if bans:
        lines.append("Banned: " + ", ".join(hero_names.get(i, str(i)) for i in bans))

    lines.append("--- End Draft State ---")
    return "\n".join(lines)


def chat(message: str, draft_context: dict | None = None) -> str:
    """Send a message to the agent, optionally with current draft state as context."""
    system = _BASE_SYSTEM_PROMPT
    if draft_context:
        system = system + "\n\n" + _draft_context_block(draft_context)

    result = graph.invoke(
        {
            "messages": [
                SystemMessage(content=system),
                HumanMessage(content=message),
            ]
        }
    )
    return result["messages"][-1].content


def explain_draft(top_heroes: list[dict], draft_context: dict) -> str:
    """Generate a concise Top 3 analysis for the given pre-scored hero list."""
    hero_lines = "\n".join(
        f"{i + 1}. {h['name']} "
        f"(counter {h['counter_score']:+.3f}, base WR {h['base_score']:+.3f})"
        for i, h in enumerate(top_heroes[:3])
    )
    message = (
        f"The top 3 algorithmically recommended picks for this draft are:\n{hero_lines}\n\n"
        "Write exactly 3 lines — one per hero — in this format:\n"
        "[Hero Name]: [one sentence, ≤15 words, why it's strong in this specific draft]\n\n"
        "Be concrete: name enemy heroes countered, notable win-rate advantage, or "
        "team synergy. You may call get_hero_matchups for more detail if useful. "
        "No intro, no filler."
    )
    return chat(message, draft_context)


if __name__ == "__main__":
    print("Dota 2 Coach — type 'quit' to exit\n")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue
        print(f"\nCoach: {chat(user_input)}\n")
