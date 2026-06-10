from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

load_dotenv()

MODEL = "claude-opus-4-8"
SYSTEM_PROMPT = "You are an expert Dota 2 coach. Help the user improve their gameplay with data-driven advice."


@tool
def get_hero_winrate(hero_name: str) -> str:
    """Get the current win rate for a Dota 2 hero."""
    # Stub — replace with real data source
    return f"{hero_name} has a 51.3% win rate in the current patch."


@tool
def get_counter_picks(hero_name: str) -> str:
    """Get strong counter-picks against a given Dota 2 hero."""
    # Stub — replace with real data source
    return f"Strong counters to {hero_name}: Bane, Silencer, Doom."


tools = [get_hero_winrate, get_counter_picks]

llm = ChatAnthropic(
    model=MODEL,
    thinking={"type": "adaptive"},
)

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
        response = chat(user_input)
        print(f"\nCoach: {response}\n")
