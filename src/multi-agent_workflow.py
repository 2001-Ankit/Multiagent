import json
import os
import re
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

from src.delivery_agent.email_tool import send_email  # noqa: E402
from src.delivery_agent.formatting_tool import format_delivery_message  # noqa: E402
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
    commander_routed: bool
    search_complete: bool
    email_sent: bool


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

COMMANDER_ROUTER_PROMPT = """You are CommanderAgent, the workflow orchestrator.
Decide whether the user's request needs live/external research before answering.

Route to search_agent when the user asks for:
- latest, current, recent, today, news, reports, market/prices, jobs, vacancies
- URLs, sources, evidence, comparisons, or anything likely to change over time
- any factual topic where live verification would improve accuracy

Route to delivery_agent when the answer can be produced from general reasoning
without live research, such as drafting, explaining code, summarizing supplied text,
or giving stable conceptual information.

Return JSON only:
{"next_node":"search_agent" or "delivery_agent","reason":"short reason"}
"""

COMMANDER_PROMPT = """You are CommanderAgent.
The SearchAgent has researched the user's question.
Use the user request and gathered search results to write the final answer.
Be clear, factual, and include useful source URLs from the tool results.
Avoid markdown tables; use clear headings and readable bullet points when helpful.
Do not call tools.
"""

DIRECT_ANSWER_PROMPT = """You are CommanderAgent.
Answer the user's request directly because live research is not required.
Be clear, concise, and structure the response with readable headings or bullets
when helpful. Avoid markdown tables unless the user explicitly asks for a table.
Do not mention internal routing or agents.
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
    if state.get("search_complete", False):
        safe_print("\n[TRACE] SearchAgent -> Commander")
        response = llm.invoke(
            [SystemMessage(content=COMMANDER_PROMPT), *state["messages"]]
        )
        safe_print("[TRACE] Commander produced the final answer from research.")
        return {
            "messages": [response],
            "next_node": "delivery_agent",
        }

    if not state.get("commander_routed", False):
        decision = decide_commander_route(state)
        if decision["next_node"] == "search_agent":
            safe_print(f"\n[TRACE] Commander -> SearchAgent: {decision['reason']}")
            return {
                "next_node": "search_agent",
                "commander_routed": True,
            }

        safe_print(f"\n[TRACE] Commander answering directly: {decision['reason']}")
        response = llm.invoke(
            [SystemMessage(content=DIRECT_ANSWER_PROMPT), *state["messages"]]
        )
        safe_print("[TRACE] Commander produced the direct final answer.")
        return {
            "messages": [response],
            "next_node": "delivery_agent",
            "commander_routed": True,
        }

    response = AIMessage(
        content="I could not decide which workflow path to use for this request."
    )
    safe_print("[TRACE] Commander produced the final answer.")
    return {
        "messages": [response],
        "next_node": "delivery_agent",
    }


def route_from_commander(
    state: AgentState,
) -> Literal["search_agent", "delivery_agent"]:
    return state["next_node"]


def decide_commander_route(state: AgentState) -> dict[str, str]:
    user_question = str(state["messages"][0].content)
    try:
        response = llm.invoke(
            [
                SystemMessage(content=COMMANDER_ROUTER_PROMPT),
                ("user", user_question),
            ]
        )
        decision = parse_route_decision(str(response.content))
        if decision["next_node"] in {"search_agent", "delivery_agent"}:
            return decision
    except Exception as exc:
        safe_print(f"\n[TRACE] Commander routing fallback used: {exc}")

    if looks_like_live_research_request(user_question):
        return {
            "next_node": "search_agent",
            "reason": "request appears to need current or sourced information",
        }

    return {
        "next_node": "delivery_agent",
        "reason": "request can be answered without live research",
    }


def parse_route_decision(content: str) -> dict[str, str]:
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise ValueError("router response did not contain JSON")

    parsed = json.loads(match.group(0))
    return {
        "next_node": str(parsed.get("next_node", "")).strip(),
        "reason": str(parsed.get("reason", "no reason provided")).strip(),
    }


def looks_like_live_research_request(question: str) -> bool:
    live_terms = (
        "latest",
        "recent",
        "current",
        "today",
        "now",
        "news",
        "report",
        "reports",
        "job",
        "jobs",
        "vacancy",
        "vacancies",
        "price",
        "market",
        "source",
        "sources",
        "url",
        "link",
        "links",
    )
    lowered = question.lower()
    return any(term in lowered for term in live_terms)


def delivery_agent(state: AgentState):
    recipient = os.environ.get("DELIVERY_EMAIL_TO") or os.environ.get("EMAIL_TO")
    if not recipient:
        safe_print(
            "\n[TRACE] DeliveryAgent skipped email: set DELIVERY_EMAIL_TO in .env."
        )
        return {"email_sent": False}

    final_answer = state["messages"][-1].content
    original_question = state["messages"][0].content

    try:
        formatted_payload = format_delivery_message.invoke(
            {
                "question": str(original_question),
                "answer": str(final_answer),
                "channel": "email",
            }
        )
        email_payload = json.loads(formatted_payload)
        subject = email_payload["subject"]
        body = email_payload["body"]
        safe_print("\n[TRACE] DeliveryAgent formatted message for email.")
    except Exception as exc:
        safe_print(f"\n[TRACE] DeliveryAgent formatting fallback used: {exc}")
        subject = f"Agent answer: {str(original_question)[:60]}"
        body = str(final_answer)

    try:
        result = send_email.invoke(
            {
                "to_email": recipient,
                "subject": subject,
                "body": body,
            }
        )
        safe_print(f"\n[TRACE] DeliveryAgent: {result}")
        return {"email_sent": True}
    except Exception as exc:
        safe_print(f"\n[TRACE] DeliveryAgent failed to send email: {exc}")
        return {"email_sent": False}


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
graph.add_node("delivery_agent", delivery_agent)

graph.add_edge(START, "commander")
graph.add_conditional_edges(
    "commander",
    route_from_commander,
    {
        "search_agent": "search_agent",
        "delivery_agent": "delivery_agent",
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
graph.add_edge("delivery_agent", END)

app = graph.compile()


def run_agent(question: str):
    return app.invoke(
        {
            "messages": [("user", question)],
            "next_node": "",
            "commander_routed": False,
            "search_complete": False,
            "email_sent": False,
        },
        config={"recursion_limit": 15},
    )


if __name__ == "__main__":
    query = "Latest Information news and field in the field of AI"
    result = run_agent(query)
    safe_print("\nFinal answer:")
    safe_print(result["messages"][-1].content)
