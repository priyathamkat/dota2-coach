from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool

load_dotenv()

MODEL = "claude-opus-4-8"


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

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an expert Dota 2 coach. Help the user improve their gameplay with data-driven advice."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)


def chat(message: str) -> str:
    result = agent_executor.invoke({"input": message})
    return result["output"]


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
