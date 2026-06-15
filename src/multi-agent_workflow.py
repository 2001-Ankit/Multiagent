import os
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.search_agent.tools import (  # noqa: E402
    extract_url_content,
    search_books,
    search_images,
    search_information,
    search_news,
    search_videos,
)

load_dotenv(override=True)


class AgentState(MessagesState):
    next_node: str
    search_complete: bool


SEARCH_TOOLS = [
    search_information,
    search_images,
    search_videos,
    search_news,
    search_books,
    extract_url_content,
]

MAX_TOOL_ROUNDS = 3

SEARCH_PROMPT = """You are SearchAgent.
Use the available tools to research the user's request.
Choose the most relevant search tool and include useful URLs.
Do not repeat an identical failed search.
After gathering enough evidence, provide a concise research summary.
"""

COMMANDER_PROMPT = """You are CommanderAgent.
The SearchAgent has researched the user's question.
Use the user request and gathered search results to write the final answer.
Be clear, factual, and include useful source URLs from the tool results.
Do not call tools.
"""


def safe_print(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding))


llm = ChatOpenAI(
    model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
    temperature=0,
)
search_llm = llm.bind_tools(SEARCH_TOOLS)
search_tool_node = ToolNode(SEARCH_TOOLS)


def commander_agent(state: AgentState):
    if not state.get("search_complete", False):
        safe_print("\n[TRACE] Commander -> SearchAgent")
        return {"next_node": "search_agent"}

    safe_print("\n[TRACE] SearchAgent -> Commander")
    response = llm.invoke(
        [SystemMessage(content=COMMANDER_PROMPT), *state["messages"]]
    )
    safe_print("[TRACE] Commander produced the final answer.")
    return {
        "messages": [response],
        "next_node": "finish",
    }


def route_from_commander(
    state: AgentState,
) -> Literal["search_agent", "finish"]:
    return state["next_node"]


def search_agent(state: AgentState):
    tool_rounds = count_tool_rounds(state)

    if tool_rounds >= MAX_TOOL_ROUNDS:
        response = AIMessage(content=build_tool_limit_answer(state["messages"]))
    else:
        response = search_llm.invoke(
            [SystemMessage(content=SEARCH_PROMPT), *state["messages"]]
        )

    if response.tool_calls:
        safe_print("\n[TRACE] SearchAgent requested tools:")
        for tool_call in response.tool_calls:
            safe_print(f"- {tool_call['name']} args={tool_call['args']}")
        return {"messages": [response]}

    safe_print("\n[TRACE] SearchAgent completed its research.")
    return {
        "messages": [response],
        "search_complete": True,
    }


def route_after_search(
    state: AgentState,
) -> Literal["tools", "commander"]:
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return "commander"


def traced_search_tools(state: AgentState):
    result = search_tool_node.invoke(state)

    safe_print("\n[TRACE] Search tools executed:")
    for message in result["messages"]:
        tool_name = getattr(message, "name", "unknown_tool")
        content = str(message.content)
        preview = content[:500] + ("..." if len(content) > 500 else "")
        safe_print(f"- {tool_name} returned:\n{preview}")

    return result


def count_tool_rounds(state: AgentState) -> int:
    return sum(
        1 for message in state["messages"] if getattr(message, "type", None) == "tool"
    )


def build_tool_limit_answer(messages) -> str:
    tool_messages = [
        message for message in messages if getattr(message, "type", None) == "tool"
    ]
    if not tool_messages:
        return "SearchAgent could not collect results."

    sections = ["SearchAgent gathered these results:", ""]
    for message in tool_messages:
        tool_name = getattr(message, "name", "unknown_tool")
        content = str(message.content)
        sections.append(f"{tool_name}:\n{content[:2000]}")
        sections.append("")

    return "\n".join(sections)


graph = StateGraph(AgentState)
graph.add_node("commander", commander_agent)
graph.add_node("search_agent", search_agent)
graph.add_node("tools", traced_search_tools)

graph.add_edge(START, "commander")
graph.add_conditional_edges(
    "commander",
    route_from_commander,
    {
        "search_agent": "search_agent",
        "finish": END,
    },
)
graph.add_conditional_edges(
    "search_agent",
    route_after_search,
    {
        "tools": "tools",
        "commander": "commander",
    },
)
graph.add_edge("tools", "search_agent")

app = graph.compile()


def run_agent(question: str):
    return app.invoke(
        {
        "messages": [("user", question)],
            "next_node": "",
            "search_complete": False,
        },
        config={"recursion_limit": 15},
    )


if __name__ == "__main__":
    query = "Job vacancy AI in today in Nepal"
    result = run_agent(query)
    safe_print("\nFinal answer:")
    safe_print(result["messages"][-1].content)
