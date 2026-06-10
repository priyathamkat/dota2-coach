import httpx
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from opendota import (
    OPENDOTA_BASE, RANK_LABELS,
    _params, _heroes, _find_hero,
    fetch_hero_stats,
)

load_dotenv()

MODEL = "claude-sonnet-4-6"
SYSTEM_PROMPT = "You are an expert Dota 2 coach. Help the user improve their gameplay with data-driven advice."


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

    MIN_GAMES = 200
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
        f"Countered by (worst winrate against):",
        *fmt(scored[:5]),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

tools = [get_hero_winrates, get_hero_matchups]

llm = ChatAnthropic(model=MODEL, thinking={"type": "adaptive"})
graph = create_react_agent(llm, tools=tools)


def chat(message: str) -> str:
    result = graph.invoke({
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=message),
        ]
    })
    return result["messages"][-1].content


if __name__ == "__main__":
    print("Dota 2 Coach — type 'quit' to exit\n")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue
        print(f"\nCoach: {chat(user_input)}\n")
