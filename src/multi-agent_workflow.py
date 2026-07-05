import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Callable

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.delivery_agent.email_tool import send_email  # noqa: E402
from src.delivery_agent.formatting_tool import format_delivery_message  # noqa: E402
from src.delivery_agent.telegram_tool import send_telegram_message  # noqa: E402
from src.delivery_agent.discord_tool import send_discord_message  # noqa: E402
from src.delivery_agent.whatsapp_tool import send_whatsapp_message  # noqa: E402
from src.finance_agent.tools import (  # noqa: E402
    get_company_overview,
    get_crypto_rate,
    get_forex_rate,
    get_stock_history,
    get_stock_quote,
    search_finance_news,
    search_macro_finance_context,
    search_nepal_finance,
)
from src.academic_agent.tools import (  # noqa: E402
    find_funding_and_scholarships,
    find_us_professors,
    find_us_programs,
    get_professor_recent_work,
)
from src.job_finder_agent.tools import (  # noqa: E402
    get_my_resume,
    search_jobs_indeed,
    search_jobs_web,
)
from src.learning_agent.tools import (  # noqa: E402
    find_learning_resources,
    find_practice_projects,
    research_role_skills,
)
from src.market_opportunity_agent.tools import (  # noqa: E402
    find_market_gaps,
    research_competitors,
    research_demand_and_funding,
    research_market_trends,
)
from src.news_agent.tools import fetch_live_updates, fetch_news_section  # noqa: E402
from src.content_agent.tools import (  # noqa: E402
    find_trending_hooks,
    research_content_angles,
)
from src.price_watch_agent.tools import search_product_price  # noqa: E402
from src.scholarship_agent.tools import (  # noqa: E402
    find_country_specific_funding,
    find_scholarships,
    get_scholarship_details,
)
from src.travel_agent.tools import (  # noqa: E402
    research_cost_of_living,
    research_flights,
    research_visa_requirements,
)
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
    # Public conversation: user request + final composed answer.
    # Per-step scratch space for the active specialist's tool loop.
    work_messages: Annotated[list, add_messages]
    plan: list
    step_index: int
    step_results: list
    awaiting_result: bool
    current_agent: str
    delivery_channel: str
    auto_deliver: bool
    email_sent: bool
    delivered: bool


# --------------------------------------------------------------------------- #
# Tool sets
# --------------------------------------------------------------------------- #
SEARCH_TOOLS = [
    search_information,
    search_images,
    search_videos,
    search_news,
    search_books,
    extract_url_content,
]

FINANCE_TOOLS = [
    get_stock_quote,
    get_company_overview,
    get_stock_history,
    get_forex_rate,
    get_crypto_rate,
    search_finance_news,
    search_macro_finance_context,
    search_nepal_finance,
]

NEWS_TOOLS = [fetch_news_section, fetch_live_updates]

ACADEMIC_TOOLS = [
    find_us_professors,
    get_professor_recent_work,
    find_us_programs,
    find_funding_and_scholarships,
    search_information,
    extract_url_content,
]

JOB_FINDER_TOOLS = [
    get_my_resume,
    search_jobs_web,
    search_jobs_indeed,
    extract_url_content,
    search_information,
]

MARKET_TOOLS = [
    research_market_trends,
    find_market_gaps,
    research_competitors,
    research_demand_and_funding,
    search_information,
    extract_url_content,
]

LEARNING_TOOLS = [
    get_my_resume,
    research_role_skills,
    find_learning_resources,
    find_practice_projects,
    search_information,
]

SCHOLARSHIP_TOOLS = [
    find_scholarships,
    get_scholarship_details,
    find_country_specific_funding,
    search_information,
    extract_url_content,
]

TRAVEL_TOOLS = [
    research_visa_requirements,
    research_cost_of_living,
    research_flights,
    search_information,
    extract_url_content,
]

CONTENT_TOOLS = [
    research_content_angles,
    find_trending_hooks,
    get_my_resume,
    search_information,
]

PRICE_WATCH_TOOLS = [
    get_stock_quote,
    get_crypto_rate,
    get_forex_rate,
    search_product_price,
]

CANDIDATE_COUNTRY = os.environ.get("CANDIDATE_COUNTRY", "Nepal").strip() or "Nepal"


def _load_user_profile() -> str:
    """A persistent 'about me' the agents can personalize with, read once at start.

    Priority: USER_PROFILE env -> data/profile.md. Empty string if neither exists.
    """
    env_profile = os.environ.get("USER_PROFILE", "").strip()
    if env_profile:
        return env_profile
    profile_path = PROJECT_ROOT / "data" / "profile.md"
    if profile_path.exists():
        return profile_path.read_text(encoding="utf-8", errors="replace").strip()
    return ""


USER_PROFILE = _load_user_profile()


def _profile_block() -> str:
    if not USER_PROFILE:
        return ""
    return (
        "\n\nAbout the user (personalize your answer to this; do not repeat it back "
        f"verbatim):\n{USER_PROFILE}\n"
    )


def with_profile(prompt: str) -> str:
    return prompt + _profile_block()

MAX_COMMANDER_CONTEXT_CHARS = 9000
MAX_TOOL_LIMIT_CHARS = 800
MAX_PLAN_STEPS = 5
DEFAULT_DELIVERY_CHANNEL = os.environ.get("DELIVERY_CHANNEL", "email").lower().strip()


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
SEARCH_PROMPT = """You are SearchAgent.
Use the available tools to research the user's request.
Choose the most relevant search tool and include useful URLs.
Do not repeat an identical failed search.
After gathering enough evidence, provide a concise research summary.
"""

FINANCE_PROMPT = """You are FinanceAgent, a practical financial analyst.
Use the finance tools to gather market data, company fundamentals, forex/crypto
rates, historical price/volume records, finance news, and Nepal/NEPSE context
when relevant.

Rules:
- You may give clear, specific, fact-based opinions and suggestions when the
  user asks what to watch, buy, avoid, trade, or invest in.
- Frame suggestions as evidence-based research, not personalized financial advice.
- Never guarantee profit, returns, safety, or a buy/sell outcome.
- Cite source URLs or data timestamps when available.
- For stock or trading questions, use historical price/volume data when possible
  and discuss trend, momentum, valuation, demand/supply signals, volume behavior,
  support/resistance areas if inferable, and catalyst/news context.
- When politics, geopolitics, inflation, interest rates, oil, currencies, trade,
  regulation, elections, war, sanctions, or supply chains may affect the answer,
  use macro context research and explain the transmission path into markets.
- If asked what to buy or invest in, provide a ranked view or specific candidates
  when evidence supports it. Include what to do next, such as watch, wait, avoid,
  accumulate gradually, or research further.
- Use real-world examples whenever they make the explanation more useful. Prefer
  sourced current examples from tools; if using a historical example from general
  knowledge, label it as historical context.
- Separate facts, market data, real-world examples, opinion, suggested action,
  risks, and what to watch.
- Be explicit about uncertainty and what would change the view.
- For Nepal or NEPSE requests, use search_nepal_finance.

After gathering enough evidence, provide a concise research memo with a specific
view rather than a vague answer.
"""

NEWS_PROMPT = """You are NewsAgent, a daily news editor.
The user wants a daily briefing organized into clear sections.

Use the fetch_news_section tool once per requested section/topic. If the user did
not name sections, cover: Finance, Politics, and Sports.
Respect any extra topics the user names (e.g. technology, Nepal, world).

If the user asks a broad "what's going on / news for today" question, also cover a
Top/World section for the biggest developing stories.

Rules:
- Call fetch_news_section once per section (finance, politics, sports). Do NOT call
  the same section twice. That is 3 calls for a standard briefing, plus at most one
  fetch_live_updates for active sports. Then write the digest.
- Call fetch_news_section separately for each section so headlines stay grouped.
- For sports, also call fetch_live_updates for major ongoing events (e.g. an active
  World Cup, finals, or tournaments) so you can report current scores, results, and
  standings, not just headlines.
- Use fetch_live_updates for any fast-moving situation where the latest state
  (scores, casualties, decisions, counts) matters more than a dated headline.
- Do not invent headlines, scores, or numbers; only use what the tools return.
- After gathering everything, write a clean digest with one heading per section.
- Under each section include AT LEAST 4-5 separate headlines (more if the tools
  returned them). Never fewer than 4 per section unless the tool truly returned less.
- Format every headline as three lines:
    1) the headline text
    2) a one-sentence description of what happened
    3) the source URL on its own line (always include it; never drop the URL)
- Put live scores/results at the top of the sports section.
- Keep it skimmable. No markdown tables.
"""

ACADEMIC_PROMPT = """You are AcademicAgent, an advisor for graduate study in the
United States. You help a prospective student find US universities and, above all,
professors whose research aligns with the student's interests.

Use the student's background and stated research interest from the request. If key
details are missing (degree level, field, subfield, target intake), state the
reasonable assumptions you made.

Workflow:
- Use find_us_professors to surface faculty/labs in the student's research area.
- Use get_professor_recent_work to confirm how a specific professor's current work
  overlaps with the student's interest before recommending them.
- Use find_us_programs for admission requirements, deadlines, and standardized tests.
- Use find_funding_and_scholarships for assistantships/fellowships when relevant.
- Use search_information / extract_url_content to open a faculty or program page for
  detail.

Output a ranked shortlist of professor matches. For each: professor name (if found),
university, lab/group, their research focus, and an explicit "Why this matches you"
line connecting their work to the student's interest. Include the source URL for
each. Then give program requirements/deadlines and concrete next steps (e.g. draft a
tailored email to the professor, note application deadlines, prepare test scores).
Only use facts from the tools; include URLs. No markdown tables.
"""

JOB_FINDER_PROMPT = f"""You are JobFinderAgent. You find jobs that match the
candidate, check eligibility, tailor their resume, and draft outreach.

The candidate is based in {CANDIDATE_COUNTRY}.

Workflow:
1. Call get_my_resume first to ground everything in the candidate's real skills,
   experience, seniority, and domain. If no resume is available, proceed from the
   user's stated background but say the resume was missing.
2. Use search_jobs_web to source roles across many boards. Also call
   search_jobs_indeed for extra reach; if it reports it is not configured, just
   rely on web results.
3. For promising roles, use extract_url_content to open the listing and read the
   real requirements, location, and application deadline.

Eligibility (critical): the candidate is in {CANDIDATE_COUNTRY}. Flag anything that
blocks them, for example:
- "Remote (US only)" / region-locked remote / "must reside in <country>".
- Roles requiring existing work authorization or citizenship with no visa sponsorship.
- Onsite roles with no relocation/sponsorship.
Mark each role as Eligible, Likely eligible, or Not eligible with a one-line reason.

Output, ranked best-fit first, only for eligible or likely-eligible roles:
- Company + role + location/remote type + application deadline (or "rolling"/"not stated").
- Match score and a short "why it fits your resume" line tied to specific resume points.
- Eligibility verdict + reason.
- Resume tailoring: 2-4 bullet points rewritten/emphasized for THIS role's requirements.
- A short, human, non-robotic outreach message the candidate could send (email/LinkedIn).
- The application URL.

End with a concise summary: which companies to apply to first and their deadlines.
Only use facts from the tools and resume; do not invent jobs, deadlines, or contacts.
No markdown tables.
"""

MARKET_PROMPT = f"""You are MarketOpportunityAgent. You find and evaluate business
and product opportunities for an entrepreneur.

The user's home market is {CANDIDATE_COUNTRY}; consider both local ({CANDIDATE_COUNTRY})
and global angles unless the user specifies a region.

Workflow:
- Use research_market_trends to see where the market is heading and what is growing.
- Use find_market_gaps to surface unmet needs, complaints, and whitespace.
- Use research_competitors to map who already exists and where they are weak.
- Use research_demand_and_funding to sanity-check that real demand/money exists.
- Use extract_url_content / search_information to dig into a specific source.

Output a ranked shortlist of 3-5 concrete opportunities. For each:
- Opportunity name + one-line description.
- The specific gap/pain it addresses and the evidence for it (with source URLs).
- Target customer segment.
- Why now (the trend or shift making this timely).
- Competitors and the wedge/differentiation vs them.
- Rough monetization model.
- Feasibility for a founder in {CANDIDATE_COUNTRY} (cost, skills, regulation, reach).
- Key risks and the cheapest next step to validate demand.

Rank by a blend of demand evidence, gap size, and feasibility. Be specific and
honest about weak evidence. Only use facts from the tools; include URLs. No tables.
"""

LEARNING_PROMPT = f"""You are LearningAgent. You build a focused upskilling plan to
get the user from where they are to a target role or skill.

The user is based in {CANDIDATE_COUNTRY}.

Workflow:
- Call get_my_resume to see the user's current skills and level. If unavailable,
  proceed from the user's stated background and say the resume was missing.
- Use research_role_skills to learn what the target role really requires.
- Compare required skills against the resume to find the real gaps.
- Use find_learning_resources (prefer free) and find_practice_projects for the gaps.

Output:
- A short "where you are vs the target" gap analysis grounded in the resume.
- A prioritized roadmap (phases or weeks), each with the skill, a concrete free
  resource (with URL), and a portfolio project that proves it.
- Quick wins first, then depth. Note anything the user already has so they skip it.
Only use facts from tools/resume; include URLs. No markdown tables.
"""

SCHOLARSHIP_PROMPT = f"""You are ScholarshipAgent. You find funding the user is
actually eligible for and explain how to win it.

The user is a student from {CANDIDATE_COUNTRY}.

Workflow:
- Use find_scholarships (pass nationality={CANDIDATE_COUNTRY}) and
  find_country_specific_funding for routes open to {CANDIDATE_COUNTRY} students.
- Use get_scholarship_details / extract_url_content to confirm eligibility,
  award amount, and deadline before recommending one.

For each recommended scholarship give: name + host, who it's for, whether a student
from {CANDIDATE_COUNTRY} is eligible (and why), what it covers, the deadline, and the
key application steps/documents. Rank by fit and deadline urgency. Flag anything with
a deadline in the next 60 days. Only use facts from tools; include URLs. No tables.
"""

TRAVEL_PROMPT = f"""You are TravelAgent. You help plan trips and study/work travel,
with a focus on what actually applies to the traveler.

The traveler holds a {CANDIDATE_COUNTRY} passport unless they say otherwise.

Workflow:
- Use research_visa_requirements (pass nationality={CANDIDATE_COUNTRY}) for the exact
  visa type, whether e-visa/visa-on-arrival applies, documents, fees, and processing.
- Use research_cost_of_living for a realistic monthly budget at the destination.
- Use research_flights for routes, typical fares, and airlines (you cannot book).
- Use extract_url_content to confirm details from an official/embassy page.

Output: the visa path for a {CANDIDATE_COUNTRY} citizen (with required documents and
fees), a realistic budget, flight/route options with fares, and a short step-by-step
plan with timing (e.g. when to apply for the visa). Flag any requirement that could
block or delay the trip. Only use facts from tools; include URLs. No markdown tables.
"""

CONTENT_PROMPT = f"""You are ContentAgent. You draft ready-to-post content in the
user's voice: LinkedIn posts, X/Twitter threads, and short newsletters.

The user is based in {CANDIDATE_COUNTRY}.

Workflow:
- If the post is about the user's own experience/brand, call get_my_resume for real
  details to reference.
- Use research_content_angles to ground the piece in current, real facts.
- Use find_trending_hooks to match how the topic performs on the target platform.

Output the actual post(s), ready to paste, for the platform requested (default to a
LinkedIn post plus one X variant if unspecified). Include a strong hook, a clear
body, a light call to action, and relevant hashtags. Keep it human and specific, not
generic or robotic. Offer 1-2 alternative hooks. Do not fabricate facts, quotes, or
statistics; if you reference data, cite the source URL.
"""

PRICE_WATCH_PROMPT = f"""You are PriceWatchAgent. You check current prices against a
target and say clearly whether to act.

For stocks/ETFs use get_stock_quote, for crypto use get_crypto_rate, for currency use
get_forex_rate, and for physical products use search_product_price. Currency context
for the user is {CANDIDATE_COUNTRY}.

For each item the user names:
- Report the current price (with source/timestamp when available).
- If the user gave a target/threshold, state whether it is met (e.g. "at or below
  target" / "above target") and by how much.
- Give a one-line, evidence-based read (trend/context), clearly not a guarantee.
- End with a clear verdict per item: ALERT (target hit / notable move), WATCH, or
  NO ACTION.
Be concise and factual. Do not invent prices; if a lookup fails, say so.
"""

SPECIALIST_ROUTES = {
    "search_agent": {
        "prompt": SEARCH_PROMPT,
        "tools": SEARCH_TOOLS,
        "max_rounds": 3,
        "description": (
            "non-finance requests needing current web/news research, sources, URLs, "
            "comparisons, facts, images, or videos"
        ),
    },
    "finance_agent": {
        "prompt": FINANCE_PROMPT,
        "tools": FINANCE_TOOLS,
        "max_rounds": 5,
        "description": (
            "financial markets, investing, trading, stocks, companies, sectors, forex, "
            "currencies, crypto, commodities, macro/interest-rate questions, portfolio "
            "research, market opinion, or NEPSE/Nepal finance"
        ),
    },
    "news_agent": {
        "prompt": NEWS_PROMPT,
        "tools": NEWS_TOOLS,
        "max_rounds": 8,
        "description": (
            "a daily news briefing or digest organized into sections such as finance, "
            "politics, sports (including live scores/results), world/top stories, or "
            "other named topics"
        ),
    },
    "academic_agent": {
        "prompt": ACADEMIC_PROMPT,
        "tools": ACADEMIC_TOOLS,
        "max_rounds": 6,
        "description": (
            "graduate/abroad study in the US: finding universities and matching "
            "professors/labs to a student's research interest, admission requirements, "
            "deadlines, standardized tests, funding, scholarships, and assistantships"
        ),
    },
    "job_finder_agent": {
        "prompt": JOB_FINDER_PROMPT,
        "tools": JOB_FINDER_TOOLS,
        "max_rounds": 7,
        "description": (
            "finding jobs that match the candidate's resume, checking eligibility "
            "(remote region locks, work authorization/visa for the candidate's "
            "country), tailoring the resume to a role, drafting outreach messages, and "
            "recommending which companies to apply to with deadlines"
        ),
    },
    "market_opportunity_agent": {
        "prompt": MARKET_PROMPT,
        "tools": MARKET_TOOLS,
        "max_rounds": 7,
        "description": (
            "spotting business/product/startup opportunities: market trends and size, "
            "unmet needs and gaps, competitor landscape, demand and funding signals, "
            "and evaluating which opportunity to pursue and how to validate it"
        ),
    },
    "learning_agent": {
        "prompt": LEARNING_PROMPT,
        "tools": LEARNING_TOOLS,
        "max_rounds": 6,
        "description": (
            "upskilling and learning plans: finding the skill gaps between the user's "
            "resume and a target role or skill, and building a prioritized roadmap of "
            "courses, resources, and portfolio projects to close them"
        ),
    },
    "scholarship_agent": {
        "prompt": SCHOLARSHIP_PROMPT,
        "tools": SCHOLARSHIP_TOOLS,
        "max_rounds": 6,
        "description": (
            "scholarships, fellowships, and study funding the user is eligible for by "
            "nationality/field/level, including eligibility, award, deadlines, and how "
            "to apply"
        ),
    },
    "travel_agent": {
        "prompt": TRAVEL_PROMPT,
        "tools": TRAVEL_TOOLS,
        "max_rounds": 6,
        "description": (
            "travel and relocation planning: visa requirements for the traveler's "
            "passport, cost of living, flights/fares, and a step-by-step trip plan "
            "with timing"
        ),
    },
    "content_agent": {
        "prompt": CONTENT_PROMPT,
        "tools": CONTENT_TOOLS,
        "max_rounds": 5,
        "description": (
            "drafting ready-to-post social/written content: LinkedIn posts, X/Twitter "
            "threads, newsletters, and captions, grounded in current facts and the "
            "user's own background"
        ),
    },
    "price_watch_agent": {
        "prompt": PRICE_WATCH_PROMPT,
        "tools": PRICE_WATCH_TOOLS,
        "max_rounds": 6,
        "description": (
            "checking current prices of stocks, crypto, currencies, or products "
            "against a target/threshold and giving a clear act/watch/no-action verdict"
        ),
    },
}

COMMANDER_PLAN_PROMPT = """You are CommanderAgent, the workflow orchestrator.
Break the user's request into an ordered plan of steps. Each step assigns a task
to exactly one specialist. Most requests need only one step; use multiple steps
only when the request genuinely spans different specialists.

Available specialists:
{catalog}
- direct: answer from general reasoning, no external research needed.

Also decide the delivery channel: "email", "telegram", or "whatsapp". Default to "{default_channel}"
unless the user clearly asks for a specific channel.

For every step include a short "reason" explaining why that specialist is the right
resource for the task.

Return JSON only, no prose:
{{"steps":[{{"agent":"<specialist>","task":"<clear task>","reason":"<why this specialist>"}}],
"delivery_channel":"email", "telegram", or "whatsapp"}}

Keep the plan minimal ({max_steps} steps max). Choose specialists by meaning, not
keywords."""

COMMANDER_COMPOSE_PROMPT = """You are CommanderAgent.
Your specialists have completed their tasks. Using the user's request and the
gathered results below, write the final answer for the user.

Guidelines:
- Synthesize the results into one coherent answer; do not just concatenate them.
- If the results contain finance/market analysis, use a research-memo structure
  (Snapshot, Specific View, Suggested Action, Key Evidence, Risks, What To Watch,
  Sources) and make clear it is research, not personalized financial advice, and
  never guarantee outcomes.
- If the results are a news briefing, PRESERVE it in full: keep every section
  heading and keep at least 4-5 headlines per section, each with its one-line
  description and its source URL. Do not drop, merge, or summarize away headlines
  or URLs, and do not shorten sections to a few bullets.
- Include useful source URLs and timestamps from the results.
- Be clear and readable. Avoid markdown tables unless the user explicitly asked.
- Do not mention internal routing, agents, or this instruction.
"""

DIRECT_ANSWER_PROMPT = """You are CommanderAgent.
Answer the user's task directly from general reasoning; no live research is needed.
Be clear and concise with readable headings or bullets when helpful.
Avoid markdown tables unless the user explicitly asks. Do not mention internal
routing or agents.
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


# --------------------------------------------------------------------------- #
# Commander: planner + orchestrator + composer
# --------------------------------------------------------------------------- #
def commander_agent(state: AgentState):
    plan = state.get("plan") or []
    step_index = state.get("step_index", 0)
    step_results = list(state.get("step_results") or [])
    channel = state.get("delivery_channel") or DEFAULT_DELIVERY_CHANNEL

    # 1. Build the plan on first entry.
    if not plan:
        plan, channel = build_plan(state)
        step_index = 0
        step_results = []
        safe_print("\n[TRACE] Commander selected resources for this request:")
        for i, step in enumerate(plan, start=1):
            safe_print(f"  {i}. {step['agent']}")
            safe_print(f"     task:   {step['task']}")
            safe_print(f"     reason: {step.get('reason', 'no reason provided')}")
        safe_print(f"[TRACE] Delivery channel: {channel}")

    # 2. Harvest the result of the step we just dispatched.
    if state.get("awaiting_result"):
        result_text = last_ai_content(state.get("work_messages", []))
        step_results.append(
            {
                "agent": plan[step_index]["agent"],
                "task": plan[step_index]["task"],
                "result": result_text,
            }
        )
        safe_print(
            f"[TRACE] Collected result from step {step_index + 1} "
            f"({plan[step_index]['agent']})."
        )
        step_index += 1

    # 3. Dispatch the next specialist step, if any.
    while step_index < len(plan):
        step = plan[step_index]
        agent = step["agent"]
        task = step["task"]

        if agent == "direct":
            response = llm.invoke(
                [SystemMessage(content=with_profile(DIRECT_ANSWER_PROMPT)), HumanMessage(content=task)]
            )
            step_results.append(
                {"agent": "direct", "task": task, "result": str(response.content)}
            )
            step_index += 1
            continue

        safe_print(f"\n[TRACE] Commander -> {agent} (step {step_index + 1})")
        return {
            "plan": plan,
            "step_index": step_index,
            "step_results": step_results,
            "current_agent": agent,
            "awaiting_result": True,
            "delivery_channel": channel,
            "work_messages": _reset_work_messages(state, task),
        }

    # 4. All steps done: compose the final answer.
    final_answer = compose_final_answer(state, step_results)
    safe_print("[TRACE] Commander produced the final answer.")
    return {
        "messages": [AIMessage(content=final_answer)],
        "plan": plan,
        "step_index": step_index,
        "step_results": step_results,
        "current_agent": "delivery_agent",
        "awaiting_result": False,
        "delivery_channel": channel,
    }


def route_from_commander(state: AgentState) -> str:
    return state["current_agent"]


def build_plan(state: AgentState) -> tuple[list, str]:
    user_question = str(state["messages"][0].content)
    catalog = "\n".join(
        f"- {name}: {cfg['description']}" for name, cfg in SPECIALIST_ROUTES.items()
    )
    prompt = COMMANDER_PLAN_PROMPT.format(
        catalog=catalog,
        default_channel=DEFAULT_DELIVERY_CHANNEL,
        max_steps=MAX_PLAN_STEPS,
    )

    try:
        response = llm.invoke(
            [SystemMessage(content=with_profile(prompt)), HumanMessage(content=user_question)]
        )
        plan, channel = parse_plan(str(response.content))
        if plan:
            return plan, channel
    except Exception as exc:
        safe_print(f"\n[TRACE] Commander planning fallback used: {exc}")

    return fallback_plan(user_question), DEFAULT_DELIVERY_CHANNEL


def parse_plan(content: str) -> tuple[list, str]:
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise ValueError("planner response did not contain JSON")

    parsed = json.loads(match.group(0))
    raw_steps = parsed.get("steps", [])
    channel = str(parsed.get("delivery_channel", DEFAULT_DELIVERY_CHANNEL)).lower().strip()
    if channel not in {"email", "telegram", "whatsapp", "discord"}:
        channel = DEFAULT_DELIVERY_CHANNEL

    valid_agents = set(SPECIALIST_ROUTES) | {"direct"}
    steps = []
    for raw in raw_steps[:MAX_PLAN_STEPS]:
        agent = str(raw.get("agent", "")).strip()
        task = str(raw.get("task", "")).strip()
        reason = str(raw.get("reason", "")).strip() or "no reason provided"
        if agent in valid_agents and task:
            steps.append({"agent": agent, "task": task, "reason": reason})

    return steps, channel


def fallback_plan(user_question: str) -> list:
    lowered = user_question.lower()
    news_terms = ("news", "briefing", "digest", "headlines", "daily")
    finance_terms = (
        "stock",
        "invest",
        "market",
        "crypto",
        "forex",
        "nepse",
        "portfolio",
        "trading",
    )
    academic_terms = (
        "university",
        "universities",
        "professor",
        "phd",
        "masters",
        "master's",
        "grad school",
        "graduate program",
        "scholarship",
        "study abroad",
        "admission",
    )
    job_terms = (
        "job",
        "jobs",
        "vacancy",
        "vacancies",
        "hiring",
        "role",
        "position",
        "apply",
        "resume",
        "cv",
        "career",
    )
    market_terms = (
        "market opportunity",
        "business idea",
        "startup",
        "market gap",
        "opportunity",
        "niche",
        "business opportunity",
        "product idea",
    )
    learning_terms = (
        "learn",
        "upskill",
        "roadmap",
        "course",
        "study plan",
        "skill gap",
        "how do i become",
        "tutorial",
    )
    scholarship_terms = (
        "scholarship",
        "scholarships",
        "fellowship",
        "funding",
        "fully funded",
        "financial aid",
    )
    travel_terms = (
        "visa",
        "passport",
        "flight",
        "flights",
        "travel",
        "trip",
        "relocate",
        "cost of living",
        "embassy",
    )
    content_terms = (
        "linkedin post",
        "tweet",
        "twitter",
        "x thread",
        "newsletter",
        "caption",
        "write a post",
        "draft a post",
        "social media",
    )
    price_terms = (
        "price watch",
        "watch the price",
        "alert me",
        "price of",
        "drops below",
        "goes above",
        "target price",
    )
    if any(term in lowered for term in news_terms):
        agent = "news_agent"
    elif any(term in lowered for term in scholarship_terms):
        agent = "scholarship_agent"
    elif any(term in lowered for term in content_terms):
        agent = "content_agent"
    elif any(term in lowered for term in price_terms):
        agent = "price_watch_agent"
    elif any(term in lowered for term in travel_terms):
        agent = "travel_agent"
    elif any(term in lowered for term in job_terms):
        agent = "job_finder_agent"
    elif any(term in lowered for term in market_terms):
        agent = "market_opportunity_agent"
    elif any(term in lowered for term in learning_terms):
        agent = "learning_agent"
    elif any(term in lowered for term in academic_terms):
        agent = "academic_agent"
    elif any(term in lowered for term in finance_terms):
        agent = "finance_agent"
    elif looks_like_live_research_request(lowered):
        agent = "search_agent"
    else:
        agent = "direct"
    return [
        {
            "agent": agent,
            "task": user_question,
            "reason": f"keyword fallback routed to {agent}",
        }
    ]


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


def compose_final_answer(state: AgentState, step_results: list) -> str:
    user_question = str(state["messages"][0].content)

    # Single step: return the specialist's own answer directly. It already wrote a
    # complete, well-structured response per its prompt; a second summarization pass
    # only loses detail (e.g. trims news headlines/URLs). The compose pass below is
    # reserved for genuinely merging multiple specialists.
    if len(step_results) == 1:
        return str(step_results[0]["result"])

    context_sections = []
    for entry in step_results:
        context_sections.append(
            f"[{entry['agent']}] task: {entry['task']}\n{entry['result']}"
        )
    gathered = _truncate_for_context("\n\n".join(context_sections))

    response = llm.invoke(
        [
            SystemMessage(content=with_profile(COMMANDER_COMPOSE_PROMPT)),
            HumanMessage(content=f"User request:\n{user_question}"),
            HumanMessage(content=f"Gathered specialist results:\n{gathered}"),
        ]
    )
    return str(response.content)


# --------------------------------------------------------------------------- #
# Generic specialist node + tool node factory
# --------------------------------------------------------------------------- #
def make_specialist_node(
    name: str,
    system_prompt: str,
    tools: list,
    max_rounds: int,
    finalizer=None,
):
    bound_llm = llm.bind_tools(tools)

    def node(state: AgentState):
        work = state.get("work_messages", [])
        if count_tool_rounds(work) >= max_rounds:
            # Research budget spent: force a final written answer from what was
            # gathered (using the plain model so it cannot request more tools),
            # instead of dumping raw tool output.
            finalize_prompt = with_profile(system_prompt) + (
                "\n\nYou have reached the research limit. Do NOT request any more "
                "tools. Write the complete, well-structured final answer now using "
                "only the information already gathered in the messages above."
            )
            response = llm.invoke([SystemMessage(content=finalize_prompt), *work])
            if getattr(response, "tool_calls", None):
                response = AIMessage(content=build_tool_limit_answer(work, name))
        else:
            response = bound_llm.invoke(
                [SystemMessage(content=with_profile(system_prompt)), *work]
            )

        if getattr(response, "tool_calls", None):
            safe_print(f"\n[TRACE] {name} requested tools:")
            for tool_call in response.tool_calls:
                safe_print(f"- {tool_call['name']} args={tool_call['args']}")
        else:
            # Final answer for this step. If a deterministic finalizer is configured
            # (e.g. news), use it so required detail/URLs are never trimmed.
            if finalizer is not None:
                built = finalizer(work)
                if built:
                    response = AIMessage(content=built)
            safe_print(f"\n[TRACE] {name} completed its task.")

        return {"work_messages": [response]}

    return node


def make_traced_tool_node(name: str, tools: list) -> Callable:
    tool_node = ToolNode(tools, messages_key="work_messages")

    def node(state: AgentState):
        result = tool_node.invoke(state)
        safe_print(f"\n[TRACE] {name} tools executed:")
        for message in result["work_messages"]:
            tool_name = getattr(message, "name", "unknown_tool")
            content = str(message.content)
            preview = content[:500] + ("..." if len(content) > 500 else "")
            safe_print(f"- {tool_name} returned:\n{preview}")
        return result

    return node


def make_route_after_specialist(tools_node_name: str) -> Callable:
    def route(state: AgentState) -> str:
        last_message = state["work_messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return tools_node_name
        return "commander"

    return route


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #
def delivery_agent(state: AgentState):
    if not state.get("auto_deliver", True):
        safe_print("\n[TRACE] DeliveryAgent skipped (auto_deliver disabled).")
        return {"delivered": False, "email_sent": False}

    channel = state.get("delivery_channel") or DEFAULT_DELIVERY_CHANNEL
    final_answer = str(state["messages"][-1].content)
    original_question = str(state["messages"][0].content)

    delivered = deliver_message(original_question, final_answer, channel)
    return {"delivered": delivered, "email_sent": delivered and channel == "email"}


def deliver_message(question: str, answer: str, channel: str | None = None) -> bool:
    """Deliver a message through the given channel (email/telegram/whatsapp).
    Reusable by the workflow node and by the scheduled briefing runner."""
    channel = (channel or DEFAULT_DELIVERY_CHANNEL).lower().strip()
    if channel == "telegram":
        return deliver_telegram(question, answer)
    if channel == "whatsapp":
        return deliver_whatsapp(question, answer)
    if channel == "discord":
        return deliver_discord(question, answer)
    return deliver_email(question, answer)


def deliver_discord(question: str, answer: str) -> bool:
    _, body = format_for_channel(question, answer, "chat")
    try:
        result = send_discord_message.invoke({"text": body})
        safe_print(f"\n[TRACE] DeliveryAgent (discord): {result}")
        return True
    except Exception as exc:
        safe_print(f"\n[TRACE] DeliveryAgent failed to send Discord message: {exc}")
        return False


def deliver_whatsapp(question: str, answer: str) -> bool:
    _, body = format_for_channel(question, answer, "whatsapp")
    try:
        result = send_whatsapp_message.invoke({"text": body})
        safe_print(f"\n[TRACE] DeliveryAgent (whatsapp): {result}")
        return True
    except Exception as exc:
        safe_print(f"\n[TRACE] DeliveryAgent failed to send WhatsApp message: {exc}")
        return False


def deliver_email(question: str, answer: str) -> bool:
    recipient = os.environ.get("DELIVERY_EMAIL_TO") or os.environ.get("EMAIL_TO")
    if not recipient:
        safe_print("\n[TRACE] DeliveryAgent skipped email: set DELIVERY_EMAIL_TO in .env.")
        return False

    subject, body = format_for_channel(question, answer, "email")
    try:
        result = send_email.invoke(
            {"to_email": recipient, "subject": subject, "body": body}
        )
        safe_print(f"\n[TRACE] DeliveryAgent (email): {result}")
        return True
    except Exception as exc:
        safe_print(f"\n[TRACE] DeliveryAgent failed to send email: {exc}")
        return False


def deliver_telegram(question: str, answer: str) -> bool:
    _, body = format_for_channel(question, answer, "chat")
    try:
        result = send_telegram_message.invoke({"text": body})
        safe_print(f"\n[TRACE] DeliveryAgent (telegram): {result}")
        return True
    except Exception as exc:
        safe_print(f"\n[TRACE] DeliveryAgent failed to send Telegram message: {exc}")
        return False


def format_for_channel(question: str, answer: str, channel: str) -> tuple[str, str]:
    try:
        formatted_payload = format_delivery_message.invoke(
            {"question": question, "answer": answer, "channel": channel}
        )
        payload = json.loads(formatted_payload)
        return payload["subject"], payload["body"]
    except Exception as exc:
        safe_print(f"\n[TRACE] DeliveryAgent formatting fallback used: {exc}")
        return f"Agent answer: {question[:60]}", answer


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _reset_work_messages(state: AgentState, task: str) -> list:
    """Clear the previous step's scratch messages and seed the new task."""
    removals = [
        RemoveMessage(id=m.id)
        for m in state.get("work_messages", [])
        if getattr(m, "id", None) is not None
    ]
    return [*removals, HumanMessage(content=task)]


def last_ai_content(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) == "ai" and message.content:
            return str(message.content)
    if messages:
        return str(messages[-1].content)
    return "No result was produced for this step."


def count_tool_rounds(messages: list[BaseMessage]) -> int:
    return sum(1 for message in messages if getattr(message, "type", None) == "tool")


def build_tool_limit_answer(messages: list[BaseMessage], agent_name: str) -> str:
    tool_messages = [
        message for message in messages if getattr(message, "type", None) == "tool"
    ]
    if not tool_messages:
        return f"{agent_name} could not collect results."

    sections = [f"{agent_name} gathered these results:", ""]
    for message in tool_messages:
        tool_name = getattr(message, "name", "unknown_tool")
        content = str(message.content)
        sections.append(f"{tool_name}:\n{content[:MAX_TOOL_LIMIT_CHARS]}")
        sections.append("")
    return "\n".join(sections)


_NEWS_FIELD_LABELS = ("date", "title", "body", "description", "source", "url")
_NEWS_ITEM_START = re.compile(r"^(?:(?:web|news)\s+)?\d+\.\s*(.*)$", re.IGNORECASE)


def _absorb_news_field(item: dict, text: str) -> None:
    for label in _NEWS_FIELD_LABELS:
        prefix = f"{label}:"
        if text.lower().startswith(prefix):
            item[label] = text[len(prefix):].strip()
            return


def _parse_news_block(block: str) -> tuple[str, list[dict]]:
    lines = block.splitlines()
    section = "News"
    if lines:
        head = lines[0].strip()
        if head.lower().startswith("section:"):
            section = head.split(":", 1)[1].strip()
        elif head.lower().startswith("live updates:"):
            section = head.split(":", 1)[1].strip() + " (live)"

    items: list[dict] = []
    current: dict = {}
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        match = _NEWS_ITEM_START.match(stripped)
        if match:
            if current:
                items.append(current)
            current = {}
            _absorb_news_field(current, match.group(1))
        else:
            _absorb_news_field(current, stripped)
    if current:
        items.append(current)
    return section, items


def build_news_digest(messages: list[BaseMessage], per_section: int = 5) -> str:
    """Deterministically format a news digest from the gathered tool results.

    Guarantees up to `per_section` headlines per section, each with a one-line
    description and its URL, without relying on the model to include them (and
    without spending tokens on a compose pass).
    """
    tool_messages = [m for m in messages if getattr(m, "type", None) == "tool"]
    if not tool_messages:
        return ""

    ordered_sections: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for message in tool_messages:
        section, items = _parse_news_block(str(message.content))
        if section not in grouped:
            grouped[section] = []
            ordered_sections.append(section)
        grouped[section].extend(items)

    out: list[str] = []
    for section in ordered_sections:
        rendered = []
        seen: set[str] = set()
        for item in grouped[section]:
            title = item.get("title", "").strip()
            url = item.get("url", "").strip()
            if not title:
                continue
            key = url or title
            if key in seen:
                continue
            seen.add(key)
            desc = (item.get("body") or item.get("description") or "").strip()
            block = [f"- {title}"]
            if desc:
                block.append(f"  {desc}")
            if url:
                block.append(f"  {url}")
            rendered.append("\n".join(block))
            if len(rendered) >= per_section:
                break
        if rendered:
            out.append(f"**{section}**")
            out.append("\n".join(rendered))
            out.append("")

    return "\n".join(out).strip()


# News uses a deterministic finalizer so every section keeps its headlines + URLs.
SPECIALIST_ROUTES["news_agent"]["finalizer"] = build_news_digest


def _truncate_for_context(text: str, max_chars: int = MAX_COMMANDER_CONTEXT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars].rstrip()
        + "\n\n[Context trimmed to stay within the model request limit.]"
    )


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #
def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("commander", commander_agent)
    graph.add_node("delivery_agent", delivery_agent)

    commander_routes = {"delivery_agent": "delivery_agent"}

    for name, cfg in SPECIALIST_ROUTES.items():
        tools_node_name = f"{name}_tools"
        graph.add_node(
            name,
            make_specialist_node(
                name,
                cfg["prompt"],
                cfg["tools"],
                cfg["max_rounds"],
                finalizer=cfg.get("finalizer"),
            ),
        )
        graph.add_node(tools_node_name, make_traced_tool_node(name, cfg["tools"]))
        graph.add_conditional_edges(
            name,
            make_route_after_specialist(tools_node_name),
            {tools_node_name: tools_node_name, "commander": "commander"},
        )
        graph.add_edge(tools_node_name, name)
        commander_routes[name] = name

    graph.add_edge(START, "commander")
    graph.add_conditional_edges("commander", route_from_commander, commander_routes)
    graph.add_edge("delivery_agent", END)
    return graph.compile()


app = build_graph()


def run_agent(question: str, deliver: bool = True, channel: str | None = None):
    return app.invoke(
        {
            "messages": [("user", question)],
            "work_messages": [],
            "plan": [],
            "step_index": 0,
            "step_results": [],
            "awaiting_result": False,
            "current_agent": "",
            "delivery_channel": (channel or DEFAULT_DELIVERY_CHANNEL),
            "auto_deliver": deliver,
            "email_sent": False,
            "delivered": False,
        },
        config={"recursion_limit": 50},
    )


def answer_only(question: str, channel: str | None = None) -> str:
    """Run the workflow but skip delivery; return the composed answer text.

    Used by the scheduled briefing runner to gather several sections and deliver
    them as a single message.
    """
    result = run_agent(question, deliver=False, channel=channel)
    return str(result["messages"][-1].content)


# --------------------------------------------------------------------------- #
# Proactive delivery: scheduled briefings ("it delivers", not "I ask")
# --------------------------------------------------------------------------- #
# Each briefing is a set of sections. Every section is run through the full agent
# workflow (so the commander still routes to the right specialist), the answers are
# combined into one message, and delivered a single time to your channel.
BRIEFINGS = {
    "daily": {
        "title": "Your Daily Briefing",
        "sections": [
            (
                "News",
                "Give me today's news briefing with sections for finance, politics, "
                "and sports (include live scores for major ongoing events), plus the "
                "top world stories. Keep it tight.",
            ),
            (
                "Markets watch",
                "Quick market watch: NEPSE and major global indices — the key moves "
                "and one or two things to watch today. Be concise.",
            ),
            (
                "Job matches",
                "Find up to 3 fresh remote roles I am eligible for from Nepal that "
                "match my resume. For each: company, role, why it fits, apply link, "
                "and deadline. Keep it short.",
            ),
        ],
    },
    "news": {
        "title": "Daily News",
        "sections": [
            (
                "News",
                "Give me today's news briefing with finance, politics, and sports "
                "(live scores for major events) plus top world stories.",
            ),
        ],
    },
    "jobs": {
        "title": "Job Matches",
        "sections": [
            (
                "Job matches",
                "Find up to 5 fresh roles I am eligible for from Nepal that match my "
                "resume. For each: company, role, why it fits, apply link, deadline, "
                "and a short tailored outreach message.",
            ),
        ],
    },
    "watch": {
        "title": "Price Watch",
        "sections": [
            (
                "Price watch",
                "Check these items and give an ALERT/WATCH/NO ACTION verdict for each: "
                + os.environ.get(
                    "PRICE_WATCHLIST",
                    "BTC target 60000 or below; AAPL; NVDA",
                ),
            ),
        ],
    },
}


def build_briefing(name: str) -> str | None:
    """Build a briefing's combined text without delivering it. Returns None if the
    briefing name is unknown. Reusable by any channel (CLI, Discord bot, etc.)."""
    briefing = BRIEFINGS.get(name)
    if not briefing:
        return None

    today = datetime.now().strftime("%A, %d %B %Y")
    safe_print(f"\n[BRIEFING] Building '{name}' for {today}")

    parts = [f"{briefing['title']} - {today}", ""]
    for label, prompt in briefing["sections"]:
        safe_print(f"\n[BRIEFING] Section: {label}")
        try:
            answer = answer_only(prompt)
        except Exception as exc:
            answer = f"(Could not build this section: {exc})"
        parts.append(f"=== {label} ===")
        parts.append(answer.strip())
        parts.append("")

    return "\n".join(parts).strip()


def run_briefing(name: str, channel: str | None = None) -> bool:
    text = build_briefing(name)
    if text is None:
        available = ", ".join(sorted(BRIEFINGS))
        safe_print(f"Unknown briefing '{name}'. Available: {available}")
        return False

    channel = channel or DEFAULT_DELIVERY_CHANNEL
    delivered = deliver_message(BRIEFINGS[name]["title"], text, channel)
    safe_print(f"\n[BRIEFING] Delivered via {channel}: {delivered}")
    return delivered


def _send_test_message(channel: str | None = None) -> None:
    channel = channel or DEFAULT_DELIVERY_CHANNEL
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    ok = deliver_message(
        "Test message",
        f"This is a test from your multi-agent assistant ({stamp}). "
        "If you can read this, delivery works.",
        channel,
    )
    safe_print(f"Test delivery via {channel}: {'sent' if ok else 'failed'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-agent workflow runner")
    parser.add_argument("--briefing", help=f"run + deliver a briefing: {', '.join(sorted(BRIEFINGS))}")
    parser.add_argument("--query", help="run a single one-off request through the agents")
    parser.add_argument("--channel", help="override delivery channel: email or telegram")
    parser.add_argument("--no-deliver", action="store_true", help="print instead of delivering")
    parser.add_argument("--test-delivery", action="store_true", help="send a test message and exit")
    args = parser.parse_args()

    if args.test_delivery:
        _send_test_message(args.channel)
    elif args.briefing:
        run_briefing(args.briefing, args.channel)
    elif args.query:
        if args.no_deliver:
            safe_print(answer_only(args.query, channel=args.channel))
        else:
            result = run_agent(args.query, channel=args.channel)
            safe_print("\nFinal answer:")
            safe_print(result["messages"][-1].content)
    else:
        query = "Give me today's daily news briefing with finance, politics, and sports sections."
        safe_print(answer_only(query))
