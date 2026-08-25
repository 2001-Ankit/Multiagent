import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
    ToolMessage,
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
from src.academic_agent.tracker import (  # noqa: E402
    get_university_details,
    list_universities,
)
from src.finance_agent.nepse import get_nepse_history, log_nepse_reading  # noqa: E402
from src.finance_agent.tools import (  # noqa: E402
    get_analyst_view,
    get_commodity_price,
    get_company_overview,
    get_crypto_rate,
    get_financials,
    get_forex_rate,
    get_market_snapshot,
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
from src.ghostwriter_agent.tools import (  # noqa: E402
    find_keywords_and_questions,
    research_for_content,
)
from src.job_finder_agent.tools import (  # noqa: E402
    get_my_resume,
    search_jobs_indeed,
    search_jobs_web,
    search_jobs_nepal,
    search_jobs_remote_global,
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
from src.news_agent.github_trends import fetch_trending_repos  # noqa: E402
from src.news_agent.papers import fetch_papers, foundational_papers  # noqa: E402
from src.news_agent.tools import fetch_ai_news, fetch_live_updates, fetch_news_section  # noqa: E402
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
from src import memory, observability  # noqa: E402
from src.vision_agent.tools import analyze_chart, describe_image  # noqa: E402
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
    session_id: str
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
    get_market_snapshot,
    get_stock_quote,
    get_company_overview,
    get_stock_history,
    get_financials,
    get_analyst_view,
    get_forex_rate,
    get_crypto_rate,
    get_commodity_price,
    search_finance_news,
    search_macro_finance_context,
    search_nepal_finance,
    log_nepse_reading,
    get_nepse_history,
]

NEWS_TOOLS = [
    fetch_news_section,
    fetch_ai_news,
    fetch_live_updates,
    fetch_trending_repos,
    fetch_papers,
    foundational_papers,
]

ACADEMIC_TOOLS = [
    list_universities,
    get_university_details,
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
    search_jobs_nepal,
    search_jobs_remote_global,
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

VISION_TOOLS = [
    analyze_chart,
    describe_image,
]

GHOSTWRITER_TOOLS = [
    research_for_content,
    find_keywords_and_questions,
    extract_url_content,
    get_my_resume,
    search_information,
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
    parts = []
    if USER_PROFILE:
        parts.append(
            "About the user (personalize your answer to this; do not repeat it back "
            f"verbatim):\n{USER_PROFILE}"
        )
    facts = memory.format_facts()
    if facts:
        parts.append(f"Things the user asked you to remember:\n{facts}")
    if not parts:
        return ""
    return "\n\n" + "\n\n".join(parts) + "\n"


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
- Start with get_market_snapshot for macro awareness (indices, gold, oil, the
  dollar, 10Y yield, VIX, Bitcoin) so you read the current world scenario - risk-on
  vs risk-off, rates, inflation pressure, dollar strength - before drilling in.
- Use get_commodity_price for commodity-driven effects (oil/gold/copper/gas/grains)
  and trace how they ripple from global macro down to sectors and niche markets.
- Use get_financials and get_analyst_view for company depth when relevant.

After gathering enough evidence, provide a concise research memo with a specific
view rather than a vague answer.
"""

NEWS_PROMPT = """You are NewsAgent, a daily news editor.

Beyond news you also cover AI tracking, with dedicated tools:
- foundational_papers: the papers every AI engineer should have read. Use this for
  "what should I read" - it is a curated list with verified links. Never answer
  from memory: arXiv IDs recalled rather than fetched are frequently wrong, and a
  broken link is worse than no recommendation.
- fetch_papers: recent arXiv work, with real abstracts. Use for "what is new" or
  for a specific topic.
- fetch_trending_repos: repositories gaining traction, with real star counts.
- fetch_ai_news: model releases and benchmarks.
For any paper or repo, give the link the tool returned - never one you composed.
The user wants a daily briefing organized into clear sections.

Use the fetch_news_section tool once per requested section/topic. If the user did
not name sections, cover: Finance, Politics, and Sports.
Respect any extra topics the user names (e.g. technology, Nepal, world).

If the user asks a broad "what's going on / news for today" question, also cover a
Top/World section for the biggest developing stories.

Each fetch_news_section call already returns BOTH a global block and a Nepal block
for that section, so one call per section covers both. Keep them as separate
sub-sections in the digest - global first, then Nepal.

Rules:
- Call fetch_news_section once per section (finance, politics, sports). Do NOT call
  the same section twice. That is 3 calls for a standard briefing, plus at most one
  fetch_live_updates. Then write the digest.
- SPORTS: never assume which competition is running. Read the sports headlines
  first, work out which major tournament or series is actually active right now,
  and only then call fetch_live_updates for THAT. A tournament that finished
  months ago must not be reported as live.
- Use fetch_live_updates for any fast-moving situation where the latest state
  (scores, decisions, counts) matters more than a dated headline.
- Do not invent headlines, scores, or numbers; only use what the tools return.
- If a section returned nothing, say so plainly rather than filling it.

Write each item as FOUR lines - the third is what makes this a briefing rather
than a list of links:
    1) the headline
    2) what happened, in one sentence
    3) why it matters: the consequence, the number that moved, who is affected,
       or what it changes. Never restate line 2 in other words.
    4) the source URL on its own line (always include it; never drop it)

- At least 4 items per sub-section where the tools returned that many.
- Put live scores/results at the top of the sports section.
- Lead each section with its single most consequential story, not the newest one.
- Keep it skimmable. No markdown tables.
"""

ACADEMIC_PROMPT = """You are AcademicAgent, an advisor for graduate study in the
United States. You help a prospective student find US universities and, above all,
professors whose research aligns with the student's interests.

Use the student's background and stated research interest from the request. If key
details are missing (degree level, field, subfield, target intake), state the
reasonable assumptions you made.

Workflow:
- The student keeps a SAVED SHORTLIST of programmes. When they refer to "my
  universities", "my shortlist", "the ones I saved", or ask to list, filter or
  compare them, call list_universities - and get_university_details for one
  specific university. Read the saved data before searching the web: the answer is
  usually already recorded, and searching returns generic information about the
  university rather than what they logged about it.
- Never say the shortlist is unavailable. It is a file, and these tools read it.
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
2. Source from BOTH markets - they are different searches, not one:
   - search_jobs_nepal for roles inside Nepal (merojob, jobsnepal, kumarijob and
     other local boards). Global boards barely index these.
   - search_jobs_remote_global for roles open to candidates anywhere.
   Do both unless the user asks for only one. A briefing that is only remote
   ignores the market the candidate can actually start in tomorrow; one that is
   only local ignores the pay difference.
   search_jobs_web is the broad fallback; search_jobs_indeed adds reach when
   configured, and can be skipped when it reports it is not.
3. For promising roles, use extract_url_content to open the listing and read the
   real requirements, location, and application deadline.


How a Nepal-based candidate can legally hold a "global" role - say which applies:
- Independent contractor: the common route. The company pays an invoice; the
  candidate handles their own Nepali tax and registration. Look for "contractor",
  "B2B" or "invoice" in the posting.
- Employer of Record (Deel, Remote.com, Oyster): the company hires through a
  local entity. Usually stated as "we hire globally through an EOR".
- Direct employment: normally requires a local entity in Nepal. Rare.
A role that says "W2 only", "must be on our payroll" or names one country for
employment is usually closed regardless of how remote it sounds. Say so plainly
rather than listing it as a match.
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

GHOSTWRITER_PROMPT = f"""You are GhostwriterAgent. You write publish-ready long-form
content in the user's voice: newsletters, blog posts/articles, LinkedIn posts, and
X/Twitter threads.

The user is based in {CANDIDATE_COUNTRY}.

Detect the format the user asked for (newsletter, blog, article, LinkedIn post, or
thread). If unspecified, ask yourself what best fits and pick one, stating which.

Workflow:
- Use research_for_content to ground the piece in real, current facts + sources.
- Use find_keywords_and_questions for blogs/newsletters to shape SEO headlines and
  answer real audience questions.
- Use get_my_resume only if the piece is about the user's own experience/brand.
- Use extract_url_content to pull detail from a specific source.

Output the FINISHED, ready-to-publish piece (not an outline), with:
- A strong hook/headline and skimmable structure (subheads, short paragraphs).
- Concrete, specific value; teach or inform - no fluff or filler.
- For blogs/newsletters: a title, the body, and a short meta description; weave in
  keywords naturally.
- For LinkedIn/threads: platform-native formatting and a light call to action.
- A "Sources" list of the URLs used.
Do not fabricate facts, quotes, or statistics; only use what the tools returned.
Keep it human and specific, never generic AI filler. No markdown tables.
"""

VISION_PROMPT = """You are VisionAgent. You analyze images the user provides (as a
file path or URL in the request).

- If the image is a market price chart (stock, ETF, index, crypto, forex, commodity),
  use analyze_chart to read trend, support/resistance, patterns, momentum, and give an
  evidence-based technical read (not financial advice, no guarantees).
- Otherwise use describe_image to describe it and extract any visible text.

Pass the exact image path/URL from the request to the tool. Report the tool's
findings clearly. Do not claim to see anything the tool did not report.
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
        "max_rounds": 4,
        "description": (
            "financial markets, investing, trading, stocks, companies, sectors, forex, "
            "currencies, crypto, commodities, macro/interest-rate questions, portfolio "
            "research, market opinion, or NEPSE/Nepal finance"
        ),
    },
    "news_agent": {
        "prompt": NEWS_PROMPT,
        "tools": NEWS_TOOLS,
        "max_rounds": 4,
        "description": (
            "a daily news briefing or digest organized into sections such as finance, "
            "politics, sports (including live scores/results), world/top stories, or "
            "other named topics. ALSO owns AI-industry tracking: which models were "
            "released and how they benchmark, trending GitHub repositories, and "
            "RESEARCH PAPERS - both what is new on arXiv and the foundational papers "
            "every AI engineer should read. Route any question about papers to read, "
            "recent papers, new models, or notable repos here. It fetches these from "
            "arXiv and the GitHub API, so answering directly would invent links "
            "instead of returning verified ones"
        ),
    },
    "academic_agent": {
        "prompt": ACADEMIC_PROMPT,
        "tools": ACADEMIC_TOOLS,
        "max_rounds": 4,
        "description": (
            "graduate/abroad study in the US: finding universities and matching "
            "professors/labs to a student's research interest, admission requirements, "
            "deadlines, standardized tests, funding, scholarships, and assistantships. "
            "ALSO owns the user's OWN saved university shortlist - the tracked CSV of "
            "programmes they have added, with deadlines, requirements, funding and "
            "status. Route here for anything about 'my shortlist', 'my universities', "
            "'the ones I saved', listing or filtering them, or details of a specific "
            "saved university. That data exists and only this agent can read it, so "
            "never answer directly that it is unavailable"
        ),
    },
    "job_finder_agent": {
        "prompt": JOB_FINDER_PROMPT,
        "tools": JOB_FINDER_TOOLS,
        "max_rounds": 4,
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
        "max_rounds": 4,
        "description": (
            "spotting business/product/startup opportunities: market trends and size, "
            "unmet needs and gaps, competitor landscape, demand and funding signals, "
            "and evaluating which opportunity to pursue and how to validate it"
        ),
    },
    "learning_agent": {
        "prompt": LEARNING_PROMPT,
        "tools": LEARNING_TOOLS,
        "max_rounds": 4,
        "description": (
            "upskilling and learning plans: finding the skill gaps between the user's "
            "resume and a target role or skill, and building a prioritized roadmap of "
            "courses, resources, and portfolio projects to close them"
        ),
    },
    "scholarship_agent": {
        "prompt": SCHOLARSHIP_PROMPT,
        "tools": SCHOLARSHIP_TOOLS,
        "max_rounds": 4,
        "description": (
            "scholarships, fellowships, and study funding the user is eligible for by "
            "nationality/field/level, including eligibility, award, deadlines, and how "
            "to apply"
        ),
    },
    "vision_agent": {
        "prompt": VISION_PROMPT,
        "tools": VISION_TOOLS,
        "max_rounds": 3,
        "description": (
            "analyzing an image provided as a path or URL: reading market price charts "
            "(stocks, crypto, forex, indices) for a technical view, or describing/"
            "extracting text from any other image or screenshot"
        ),
    },
    "travel_agent": {
        "prompt": TRAVEL_PROMPT,
        "tools": TRAVEL_TOOLS,
        "max_rounds": 4,
        "description": (
            "travel and relocation planning: visa requirements for the traveler's "
            "passport, cost of living, flights/fares, and a step-by-step trip plan "
            "with timing"
        ),
    },
    "content_agent": {
        "prompt": CONTENT_PROMPT,
        "tools": CONTENT_TOOLS,
        "max_rounds": 4,
        "description": (
            "short-form social content: a single LinkedIn post, an X/Twitter thread, "
            "or a caption, grounded in current facts and the user's background"
        ),
    },
    "ghostwriter_agent": {
        "prompt": GHOSTWRITER_PROMPT,
        "tools": GHOSTWRITER_TOOLS,
        "max_rounds": 4,
        "description": (
            "publish-ready long-form writing: newsletters, blog posts/articles, and "
            "longer pieces, researched and grounded with sources (ghostwriting)"
        ),
    },
    "price_watch_agent": {
        "prompt": PRICE_WATCH_PROMPT,
        "tools": PRICE_WATCH_TOOLS,
        "max_rounds": 4,
        "description": (
            "checking current prices of stocks, crypto, currencies, or products "
            "against a target/threshold and giving a clear act/watch/no-action verdict"
        ),
    },
}

COMMANDER_PLAN_PROMPT = """You are CommanderAgent, the workflow orchestrator.
Decide HOW MANY agents the request needs, WHICH ones, and HOW they should run.

Available specialists:
{catalog}
- direct: answer from general reasoning, no external research needed.

If earlier conversation is supplied, the request may be a FOLLOW-UP ("tell me more
about the second one", "compare that to X", "why?"). Resolve every such reference
using that history and write each step's task so it is fully self-contained - the
specialist running it will NOT see the conversation.

Be selective. An extra agent is only worth it if it contributes something the others
genuinely cannot. Rules:
- Never add an agent that has no input to work with. In particular, only use
  vision_agent when the request actually contains an image URL or file path.
- Never add an agent whose findings would duplicate another agent's.
- In parallel mode prefer 2-3 agents; more agents is slower and rarely better.
- If one specialist can fully satisfy the request, use "solo" - that is the norm.

Choose an execution mode:
- "solo": one specialist fully answers the request. Use this for most requests -
  do not add agents that would only pad the answer.
- "parallel": the request benefits from several DIFFERENT perspectives examined at
  the same time, then merged. Use for open/analytical questions like evaluating an
  opportunity, a decision, or a market from multiple angles. Give each agent a
  DISTINCT angle on the SAME question so their findings complement, not duplicate.
- "sequential": later steps genuinely need the OUTPUT of earlier steps (research
  first, then write it up). Each step sees the previous steps' findings.

Also decide the delivery channel: "email", "telegram", "whatsapp", or "discord".
Default to "{default_channel}" unless the user clearly asks for a specific channel.

For every step include a short "reason" explaining why that specialist is right.

Return JSON only, no prose:
{{"mode":"solo" or "parallel" or "sequential",
"steps":[{{"agent":"<specialist>","task":"<clear task>","reason":"<why this specialist>"}}],
"delivery_channel":"{default_channel}"}}

Keep the plan minimal ({max_steps} steps max). Prefer "solo" unless multiple
perspectives clearly produce a better answer. Choose specialists by meaning, not
keywords."""

COMMANDER_COMPOSE_PROMPT = """You are CommanderAgent.
Your specialists have completed their tasks. Using the user's request and the
gathered results below, write the final answer for the user.

Guidelines:
- Synthesize the results into one coherent answer; do not just concatenate them.
- When several agents examined the same question from different angles, act as the
  aggregator: merge their perspectives, call out where they AGREE (higher
  confidence), where they DISAGREE or conflict (say so explicitly and explain the
  tension), and what each angle uniquely contributed. Finish with a single clear
  conclusion or recommendation, not a list of separate opinions.
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

CRITIC_PROMPT = """You are CriticAgent, a demanding reviewer.

You are given a user's request, the raw findings several specialists produced, and a
draft answer that merged them. Improve the draft.

Check for:
- Claims in the draft that the findings do not actually support (remove or soften).
- Contradictions between specialists that the draft glossed over (surface them).
- Important findings that were dropped from the draft (add them back).
- Vague filler that should be replaced with specifics from the findings.
- Missing source URLs that exist in the findings.

Return ONLY the improved final answer for the user - no commentary about your review,
no "here is the revised version" preamble. Keep everything that was already good.
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


# The "brain" is any OpenAI-compatible endpoint. Defaults to Groq; set LLM_* in .env
# to point at NVIDIA (e.g. moonshotai/kimi-k2.6) or another provider without code
# changes. GROQ_* are kept as fallbacks for backward compatibility.
# Default to llama-3.3-70b-versatile: reliable tool-calling on Groq (the gpt-oss
# models intermittently emit malformed/misplaced tool calls that Groq rejects).
LLM_MODEL = (
    os.environ.get("LLM_MODEL")
    or os.environ.get("GROQ_MODEL")
    or "llama-3.3-70b-versatile"
)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")

llm = ChatOpenAI(
    model=LLM_MODEL,
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    temperature=0,
)


# --------------------------------------------------------------------------- #
# Fallback chain
# --------------------------------------------------------------------------- #
# Provider quotas are per-model (and per-provider), so when one model is exhausted
# for the day another still has budget. The chain is tried in order.
def _build_llm_chain() -> list[dict]:
    chain: list[dict] = [
        {
            "model": LLM_MODEL,
            "base_url": LLM_BASE_URL,
            "api_key": LLM_API_KEY,
            "client": llm,
        }
    ]

    # Same provider, different models -> separate per-model quotas.
    extra_models = os.environ.get(
        "LLM_FALLBACK_MODELS", "llama-3.1-8b-instant,openai/gpt-oss-120b"
    )
    for name in (m.strip() for m in extra_models.split(",")):
        if name and name != LLM_MODEL:
            chain.append(
                {
                    "model": name,
                    "base_url": LLM_BASE_URL,
                    "api_key": LLM_API_KEY,
                    "client": None,
                }
            )

    # Different provider entirely -> a completely separate quota pool.
    nvidia_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    nvidia_model = os.environ.get(
        "LLM_FALLBACK_NVIDIA_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5"
    ).strip()
    if nvidia_key and nvidia_model and "nvidia" not in LLM_BASE_URL:
        chain.append(
            {
                "model": nvidia_model,
                "base_url": "https://integrate.api.nvidia.com/v1",
                "api_key": nvidia_key,
                "client": None,
            }
        )

    # Google, via its OpenAI-compatible endpoint, so no new client type is needed.
    # A third provider is a third independent quota pool: when Groq's daily limit
    # is gone, every Groq model is gone with it.
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    gemini_model = os.environ.get("LLM_FALLBACK_GEMINI_MODEL", "gemini-2.5-flash").strip()
    if gemini_key and gemini_model and "googleapis" not in LLM_BASE_URL:
        chain.append(
            {
                "model": gemini_model,
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "api_key": gemini_key,
                "client": None,
            }
        )
    return chain


LLM_CHAIN = _build_llm_chain()


def _client_for(entry: dict) -> ChatOpenAI:
    """Lazily create (and cache) the client for a fallback chain entry."""
    if entry["client"] is None:
        entry["client"] = ChatOpenAI(
            model=entry["model"],
            api_key=entry["api_key"],
            base_url=entry["base_url"],
            temperature=0,
        )
    return entry["client"]


def _provider_name(base_url: str) -> str:
    if "groq" in base_url:
        return "Groq"
    if "nvidia" in base_url:
        return "NVIDIA"
    # Must precede the OpenAI check: Google's compatible endpoint ends in /openai/.
    if "googleapis" in base_url:
        return "Google"
    if "openai" in base_url:
        return "OpenAI"
    return base_url


def active_model_info() -> str:
    """One-line description of the brain LLM and its fallbacks."""
    primary = f"{LLM_MODEL} via {_provider_name(LLM_BASE_URL)}"
    fallbacks = [
        f"{entry['model']} ({_provider_name(entry['base_url'])})"
        for entry in LLM_CHAIN[1:]
    ]
    if fallbacks:
        return f"{primary} | fallbacks: {' -> '.join(fallbacks)}"
    return primary


# Log the active model once at startup so it's always visible in the console/bot logs.
safe_print(f"[CONFIG] Brain LLM: {active_model_info()}")


def _classify_error(exc: Exception) -> str:
    """transient | minute_limit | quota_exhausted | fatal."""
    text = str(exc).lower()
    if "429" in text or "rate limit" in text or "rate_limit" in text:
        # A per-day//per-month cap will not clear by waiting a few seconds, so
        # switch models instead of sleeping.
        if "per day" in text or "tpd" in text or "rpd" in text or "per month" in text:
            return "quota_exhausted"
        return "minute_limit"
    if (
        "output_parse_failed" in text
        or "could not be parsed" in text
        or "failed_generation" in text
        or "tool_use_failed" in text
        or "tool choice is none" in text
    ):
        return "transient"
    if "401" in text or "403" in text or "invalid api key" in text:
        return "quota_exhausted"  # bad/absent key for this provider: try the next
    if "model_not_found" in text or "does not exist" in text or "404" in text:
        return "quota_exhausted"
    return "fatal"


def _invoke_one(runnable, messages, retries: int, base_delay: float):
    """Invoke a single model, retrying only errors that a retry can actually fix."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return runnable.invoke(messages)
        except Exception as exc:  # noqa: BLE001 - inspect the provider message
            last_error = exc
            kind = _classify_error(exc)
            if kind in {"fatal", "quota_exhausted"} or attempt == retries - 1:
                raise

            if kind == "minute_limit":
                delay = base_delay * (attempt + 1)
                hint = re.search(r"try again in ([0-9.]+)\s*s", str(exc))
                if hint:
                    delay = float(hint.group(1)) + 0.5
                safe_print(
                    f"[retry] rate limited; waiting {min(delay, 30):.1f}s "
                    f"(attempt {attempt + 1}/{retries})"
                )
                time.sleep(min(delay, 30))
            else:
                safe_print(
                    f"[retry] model output parse failed; retrying "
                    f"(attempt {attempt + 1}/{retries})"
                )
                time.sleep(1.0)
    if last_error:
        raise last_error
    raise RuntimeError("invoke failed without an exception")


def invoke_with_fallback(messages, tools: list | None = None, retries: int = 4):
    """Invoke the brain LLM, falling back to the next model when one is exhausted.

    Quotas are per-model and per-provider, so a model that is out of daily budget is
    skipped in favour of the next entry in LLM_CHAIN instead of failing the request.
    """
    last_error: Exception | None = None
    for index, entry in enumerate(LLM_CHAIN):
        try:
            client = _client_for(entry)
        except Exception as exc:
            last_error = exc
            continue

        runnable = client.bind_tools(tools) if tools else client
        try:
            result = _invoke_one(runnable, messages, retries, 3.0)
            sent = sum(len(str(getattr(m, "content", ""))) for m in messages)
            record_token_estimate(sent + len(str(getattr(result, "content", ""))))
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            kind = _classify_error(exc)
            has_next = index < len(LLM_CHAIN) - 1
            if kind == "fatal" or not has_next:
                raise
            next_entry = LLM_CHAIN[index + 1]
            safe_print(
                f"[fallback] {entry['model']} unavailable ({kind}); "
                f"switching to {next_entry['model']}"
            )
    if last_error:
        raise last_error
    raise RuntimeError("no LLM available in the fallback chain")


def robust_invoke(runnable, messages, retries: int = 5):
    """Deprecated shim kept for any external callers.

    Prefer invoke_with_fallback(messages, tools=...) so the fallback model can be
    given the same tools.
    """
    if runnable is llm:
        return invoke_with_fallback(messages, retries=retries)
    return _invoke_one(runnable, messages, retries, 3.0)


# --------------------------------------------------------------------------- #
# Swarm: run specialists concurrently on one problem, then aggregate
# --------------------------------------------------------------------------- #
# Parallel agents multiply token usage per minute, so keep the fan-out modest on
# free provider tiers (rate-limit retries in robust_invoke absorb the rest).
SWARM_MAX_WORKERS = int(os.environ.get("SWARM_MAX_WORKERS", "3"))

# Token control. An agent re-sends its whole history every round, so raw tool output
# is the dominant cost: N rounds of accumulating results grows quadratically. Capping
# each result and compacting older ones keeps a request affordable on a free tier.
MAX_TOOL_RESULT_CHARS = int(os.environ.get("MAX_TOOL_RESULT_CHARS", "1500"))
TOOL_HISTORY_KEEP_FULL = int(os.environ.get("TOOL_HISTORY_KEEP_FULL", "2"))


# Rough daily budget guard. Providers bill by token, so a swarm can quietly consume
# a whole day's quota; when the estimate crosses the threshold we stop fanning out.
DAILY_TOKEN_BUDGET = int(os.environ.get("DAILY_TOKEN_BUDGET", "100000"))
SWARM_BUDGET_FRACTION = float(os.environ.get("SWARM_BUDGET_FRACTION", "0.6"))
_budget_lock = threading.Lock()
_budget_state = {"day": "", "tokens": 0}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def record_token_estimate(chars: int) -> None:
    """Track approximate tokens used today (~4 chars per token)."""
    with _budget_lock:
        if _budget_state["day"] != _today():
            _budget_state["day"] = _today()
            _budget_state["tokens"] = 0
        _budget_state["tokens"] += max(0, chars) // 4


def tokens_used_today() -> int:
    with _budget_lock:
        if _budget_state["day"] != _today():
            return 0
        return int(_budget_state["tokens"])


def swarm_budget_available() -> bool:
    """False once today's estimated usage passes the swarm cut-off."""
    return tokens_used_today() < DAILY_TOKEN_BUDGET * SWARM_BUDGET_FRACTION


# A fan-out costs roughly three times a solo run, so it is opt-in. The planner
# asking for "parallel" is a suggestion; these decide whether it actually happens.
SWARM_OPT_IN_ONLY = os.environ.get("SWARM_OPT_IN_ONLY", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}

_SWARM_REQUESTED = re.compile(
    r"\b(swarm|deep[\s-]?dive|in[\s-]?depth|thorough(ly)?|exhaustive|"
    r"multiple angles|several angles|different angles|every angle|"
    r"pros and cons|full analysis|comprehensive|weigh up|trade[\s-]?offs)\b",
    re.IGNORECASE,
)
_SWARM_DECLINED = re.compile(
    r"\b(quick(ly)?|briefly|brief|short answer|just tell me|one[\s-]?liner|"
    r"tl;?dr|in a sentence|simply put|keep it short)\b",
    re.IGNORECASE,
)


def swarm_intent(question: str) -> str:
    """Did the user ask for a swarm, refuse one, or say nothing either way?

    Returns "force", "block" or "auto". An explicit refusal beats an explicit
    request, because "quick pros and cons" is a request for brevity.
    """
    text = question or ""
    if _SWARM_DECLINED.search(text):
        return "block"
    if _SWARM_REQUESTED.search(text):
        return "force"
    return "auto"


def should_run_swarm(question: str, planner_mode: str, agent_count: int) -> tuple[bool, str]:
    """Decide whether to actually fan out. Returns (run_swarm, reason).

    The planner is optimistic about parallelism because more perspectives always
    look better in the abstract. It does not pay the token bill, so the decision
    lives here instead.
    """
    if agent_count < 2:
        return False, "only one viable agent"
    intent = swarm_intent(question)
    if intent == "block":
        return False, "user asked for a short answer"
    if intent == "force":
        if not swarm_budget_available():
            return False, f"user asked for depth but ~{tokens_used_today():,} tokens used today"
        return True, "user explicitly asked for a deeper look"
    if planner_mode != "parallel":
        return False, "planner chose a single specialist"
    if SWARM_OPT_IN_ONLY:
        return False, "swarm is opt-in (set SWARM_OPT_IN_ONLY=0 to let the planner decide)"
    if not swarm_budget_available():
        return False, f"~{tokens_used_today():,} tokens used today; preserving quota"
    return True, "planner asked for multiple perspectives and budget allows"


def _cap_tool_output(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS].rstrip() + "\n[...truncated]"


def compact_tool_history(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Shrink older tool results so context doesn't grow round after round.

    The newest TOOL_HISTORY_KEEP_FULL results stay intact (the agent is actively
    reasoning about them); earlier ones collapse to a one-line placeholder.
    """
    tool_positions = [
        index
        for index, message in enumerate(messages)
        if getattr(message, "type", None) == "tool"
    ]
    if len(tool_positions) <= TOOL_HISTORY_KEEP_FULL:
        return messages

    stale = set(tool_positions[:-TOOL_HISTORY_KEEP_FULL])
    compacted: list[BaseMessage] = []
    for index, message in enumerate(messages):
        if index in stale:
            content = str(message.content)
            if len(content) > 300:
                message = ToolMessage(
                    content=content[:300].rstrip() + "\n[...earlier result trimmed]",
                    tool_call_id=getattr(message, "tool_call_id", "") or "trimmed",
                    name=getattr(message, "name", "tool"),
                )
        compacted.append(message)
    return compacted


def run_specialist_standalone(
    agent_name: str,
    task: str,
    shared_context: str = "",
) -> str:
    """Run one specialist's full tool loop in isolation and return its answer.

    Self-contained (no graph state), so several of these can run in parallel
    threads. `shared_context` lets an agent see what other agents already found.
    """
    config = SPECIALIST_ROUTES.get(agent_name)
    if not config:
        return f"Unknown specialist: {agent_name}"

    tools = config["tools"]
    tools_by_name = {tool.name: tool for tool in tools}

    system_prompt = with_profile(config["prompt"])
    if shared_context.strip():
        system_prompt += (
            "\n\nFindings already gathered by other agents on this task - build on "
            "them, do not repeat their work:\n"
            f"{_truncate_for_context(shared_context, 4000)}"
        )

    messages: list[BaseMessage] = [HumanMessage(content=task)]
    trace = observability.current()
    agent_started = time.time()

    for _ in range(config["max_rounds"]):
        response = invoke_with_fallback(
            [SystemMessage(content=system_prompt), *compact_tool_history(messages)],
            tools=tools,
        )
        calls = getattr(response, "tool_calls", None)
        if not calls:
            if trace:
                trace.agent_event(agent_name, time.time() - agent_started, True)
            return str(response.content)

        messages.append(response)
        for call in calls:
            tool = tools_by_name.get(call["name"])
            tool_started = time.time()
            if tool is None:
                output = f"Unknown tool: {call['name']}"
                if trace:
                    trace.tool_event(
                        agent_name, call["name"], 0.0, False, "unknown tool"
                    )
            else:
                try:
                    output = str(tool.invoke(call["args"]))
                except Exception as exc:  # keep the loop alive on tool failure
                    output = f"Tool {call['name']} failed: {exc}"
                    if trace:
                        trace.tool_event(
                            agent_name,
                            call["name"],
                            time.time() - tool_started,
                            False,
                            str(exc),
                        )
                else:
                    if trace:
                        trace.tool_event(
                            agent_name, call["name"], time.time() - tool_started, True
                        )
            messages.append(
                ToolMessage(
                    content=_cap_tool_output(output),
                    tool_call_id=call.get("id", call["name"]),
                    name=call["name"],
                )
            )

    # Research budget spent: force a written answer from what was gathered.
    finalizer = config.get("finalizer")
    if finalizer is not None:
        built = finalizer(messages)
        if built:
            return built
    try:
        final = invoke_with_fallback(
            [
                SystemMessage(
                    content=system_prompt
                    + "\n\nYou have reached the research limit. Do NOT request more "
                    "tools. Write the complete final answer now from what you have."
                ),
                *messages,
            ],
        )
        if not getattr(final, "tool_calls", None):
            return str(final.content)
    except Exception as exc:
        safe_print(f"[swarm] {agent_name} finalize fell back: {exc}")
    return build_tool_limit_answer(messages, agent_name)


def run_swarm(steps: list[dict], shared_context: str = "") -> list[dict]:
    """Run several specialists concurrently on the same problem (ConcurrentWorkflow).

    Returns results in the original plan order so output stays deterministic.
    """
    workers = max(1, min(SWARM_MAX_WORKERS, len(steps)))
    safe_print(
        f"\n[SWARM] Dispatching {len(steps)} agents in parallel "
        f"(max {workers} at a time):"
    )
    for step in steps:
        safe_print(f"  - {step['agent']}: {step['task']}")

    results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                run_specialist_standalone, step["agent"], step["task"], shared_context
            ): index
            for index, step in enumerate(steps)
        }
        for future in futures:
            index = futures[future]
            step = steps[index]
            try:
                text = future.result()
            except Exception as exc:
                text = f"({step['agent']} failed: {exc})"
                safe_print(f"[SWARM] {step['agent']} failed: {exc}")
            else:
                safe_print(f"[SWARM] {step['agent']} finished.")
            results[index] = {
                "agent": step["agent"],
                "task": step["task"],
                "result": text,
            }

    return [results[index] for index in sorted(results)]


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
        plan, channel, mode = build_plan(state)
        step_index = 0
        step_results = []
        trace = observability.current()
        if trace:
            trace.set_plan(mode, plan, channel, active_model_info())
        safe_print(f"\n[TRACE] Brain model: {active_model_info()}")
        safe_print(f"[TRACE] Execution mode: {mode}")
        safe_print("[TRACE] Commander selected resources for this request:")
        for i, step in enumerate(plan, start=1):
            safe_print(f"  {i}. {step['agent']}")
            safe_print(f"     task:   {step['task']}")
            safe_print(f"     reason: {step.get('reason', 'no reason provided')}")
        safe_print(f"[TRACE] Delivery channel: {channel}")

        # Parallel mode: run every specialist at once, then go straight to the
        # aggregator. Nothing to dispatch through the graph one-by-one.
        swarm_steps = [step for step in plan if step["agent"] != "direct"]
        question = str(state["messages"][0].content)
        fan_out, why = should_run_swarm(question, mode, len(swarm_steps))

        if fan_out and mode != "parallel":
            # The user asked for depth explicitly; honour it over the plan.
            safe_print(f"[SWARM] Escalating to a swarm: {why}.")
            mode = "parallel"
        elif not fan_out and mode == "parallel" and len(swarm_steps) > 1:
            safe_print(f"[SWARM] Running solo instead of a swarm: {why}.")
            plan = swarm_steps[:1]
            mode = "solo"
            swarm_steps = plan

        if fan_out and len(swarm_steps) > 1:
            step_results = run_swarm(swarm_steps)
            final_answer = compose_final_answer(state, step_results)
            safe_print("[TRACE] Commander aggregated the swarm results.")
            final_answer = run_critic_pass(state, step_results, final_answer)
            return {
                "messages": [AIMessage(content=final_answer)],
                "plan": plan,
                "step_index": len(plan),
                "step_results": step_results,
                "current_agent": "delivery_agent",
                "awaiting_result": False,
                "delivery_channel": channel,
            }

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
            direct_messages: list[BaseMessage] = [
                SystemMessage(content=with_profile(DIRECT_ANSWER_PROMPT))
            ]
            direct_history = memory.format_history(state.get("session_id", "cli"))
            if direct_history:
                direct_messages.append(
                    HumanMessage(content=f"Earlier in this conversation:\n{direct_history}")
                )
            direct_messages.append(HumanMessage(content=task))
            response = invoke_with_fallback(direct_messages)
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
            "work_messages": _reset_work_messages(state, task, step_results),
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


def build_plan(state: AgentState) -> tuple[list, str, str]:
    user_question = str(state["messages"][0].content)
    catalog = "\n".join(
        f"- {name}: {cfg['description']}" for name, cfg in SPECIALIST_ROUTES.items()
    )
    prompt = COMMANDER_PLAN_PROMPT.format(
        catalog=catalog,
        default_channel=DEFAULT_DELIVERY_CHANNEL,
        max_steps=MAX_PLAN_STEPS,
    )

    # Recent turns go to the planner only: it rewrites follow-ups into
    # self-contained tasks, so specialists never pay for the history.
    history = memory.format_history(state.get("session_id", "cli"))
    planner_messages: list[BaseMessage] = [SystemMessage(content=with_profile(prompt))]
    if history:
        planner_messages.append(
            HumanMessage(content=f"Earlier in this conversation:\n{history}")
        )
    planner_messages.append(HumanMessage(content=f"New request:\n{user_question}"))

    try:
        response = invoke_with_fallback(planner_messages)
        plan, channel, mode = parse_plan(str(response.content))
        plan = filter_viable_steps(plan, user_question)
        if plan:
            if len(plan) <= 1:
                mode = "solo"
            return plan, channel, mode
    except Exception as exc:
        safe_print(f"\n[TRACE] Commander planning fallback used: {exc}")

    return fallback_plan(user_question), DEFAULT_DELIVERY_CHANNEL, "solo"


MAX_SWARM_AGENTS = int(os.environ.get("MAX_SWARM_AGENTS", "3"))
_IMAGE_HINT = re.compile(
    r"(https?://\S+\.(?:png|jpe?g|webp|gif)|\S+\.(?:png|jpe?g|webp|gif)\b)", re.IGNORECASE
)


def filter_viable_steps(steps: list, user_question: str) -> list:
    """Drop agents that cannot contribute, so the swarm doesn't burn budget on them.

    The planner sometimes adds a specialist whose required input is missing (most
    often vision_agent with no image), which costs tokens and returns nothing useful.
    """
    viable = []
    for step in steps:
        agent = step.get("agent", "")
        if agent == "vision_agent" and not _IMAGE_HINT.search(user_question):
            safe_print("[TRACE] Dropped vision_agent from plan: no image in the request.")
            continue
        viable.append(step)

    if len(viable) > MAX_SWARM_AGENTS:
        safe_print(
            f"[TRACE] Trimmed plan from {len(viable)} to {MAX_SWARM_AGENTS} agents."
        )
        viable = viable[:MAX_SWARM_AGENTS]

    # Never return an empty plan.
    return viable or steps[:1]


def parse_plan(content: str) -> tuple[list, str, str]:
    """Parse the planner JSON into (steps, delivery_channel, execution_mode)."""
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise ValueError("planner response did not contain JSON")

    parsed = json.loads(match.group(0))
    raw_steps = parsed.get("steps", [])
    channel = str(parsed.get("delivery_channel", DEFAULT_DELIVERY_CHANNEL)).lower().strip()
    if channel not in {"email", "telegram", "whatsapp", "discord"}:
        channel = DEFAULT_DELIVERY_CHANNEL

    mode = str(parsed.get("mode", "solo")).lower().strip()
    if mode not in {"solo", "parallel", "sequential"}:
        mode = "solo"

    valid_agents = set(SPECIALIST_ROUTES) | {"direct"}
    steps = []
    for raw in raw_steps[:MAX_PLAN_STEPS]:
        agent = str(raw.get("agent", "")).strip()
        task = str(raw.get("task", "")).strip()
        reason = str(raw.get("reason", "")).strip() or "no reason provided"
        if agent in valid_agents and task:
            steps.append({"agent": agent, "task": task, "reason": reason})

    # A single step is solo by definition, whatever the model claimed.
    if len(steps) <= 1:
        mode = "solo"

    return steps, channel, mode


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
    ghostwriter_terms = (
        "newsletter",
        "blog",
        "article",
        "ghostwrite",
        "ghost write",
        "write a piece",
        "long form",
        "long-form",
        "essay",
    )
    content_terms = (
        "linkedin post",
        "tweet",
        "twitter",
        "x thread",
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
    # Writing intent ("write a newsletter/blog/post") wins over the topic keyword.
    if any(term in lowered for term in ghostwriter_terms):
        agent = "ghostwriter_agent"
    elif any(term in lowered for term in content_terms):
        agent = "content_agent"
    elif any(term in lowered for term in news_terms):
        agent = "news_agent"
    elif any(term in lowered for term in scholarship_terms):
        agent = "scholarship_agent"
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


ENABLE_CRITIC = os.environ.get("ENABLE_CRITIC", "true").strip().lower() not in {
    "0",
    "false",
    "off",
}


def run_critic_pass(state: AgentState, step_results: list, draft: str) -> str:
    """One reviewer pass over a merged swarm answer.

    Much cheaper than multi-round debate but catches the main failure modes:
    unsupported claims, buried contradictions, dropped findings, missing sources.
    Falls back to the draft on any failure so a critic error never loses the answer.
    """
    if not ENABLE_CRITIC or not draft.strip():
        return draft

    user_question = str(state["messages"][0].content)
    findings = _truncate_for_context(
        "\n\n".join(f"[{e['agent']}] {e['result']}" for e in step_results), 6000
    )
    started = time.time()
    try:
        response = invoke_with_fallback(
            [
                SystemMessage(content=with_profile(CRITIC_PROMPT)),
                HumanMessage(content=f"User request:\n{user_question}"),
                HumanMessage(content=f"Specialist findings:\n{findings}"),
                HumanMessage(content=f"Draft answer to improve:\n{draft}"),
            ],
        )
    except Exception as exc:
        safe_print(f"[TRACE] Critic pass skipped: {exc}")
        return draft

    revised = str(response.content).strip()
    trace = observability.current()
    if trace:
        trace.agent_event("critic", time.time() - started, bool(revised))
    if len(revised) < len(draft) * 0.5:
        # A drastically shorter result usually means the critic misfired.
        safe_print("[TRACE] Critic output looked truncated; keeping the draft.")
        return draft
    safe_print("[TRACE] Critic pass refined the answer.")
    return revised


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

    response = invoke_with_fallback(
        [
            SystemMessage(content=with_profile(COMMANDER_COMPOSE_PROMPT)),
            HumanMessage(content=f"User request:\n{user_question}"),
            HumanMessage(content=f"Gathered specialist results:\n{gathered}"),
        ],
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
    def node(state: AgentState):
        work = state.get("work_messages", [])
        node_started = time.time()
        if count_tool_rounds(work) >= max_rounds:
            # Research budget spent: force a final written answer from what was
            # gathered (using the plain model so it cannot request more tools),
            # instead of dumping raw tool output.
            finalize_prompt = with_profile(system_prompt) + (
                "\n\nYou have reached the research limit. Do NOT request any more "
                "tools. Write the complete, well-structured final answer now using "
                "only the information already gathered in the messages above."
            )
            try:
                response = invoke_with_fallback([SystemMessage(content=finalize_prompt), *work])
                if getattr(response, "tool_calls", None):
                    response = AIMessage(content=build_tool_limit_answer(work, name))
            except Exception as exc:
                # Never crash the whole request if the finalize call misbehaves;
                # fall back to a plain summary of what was gathered.
                safe_print(f"\n[TRACE] {name} finalize fell back: {exc}")
                response = AIMessage(content=build_tool_limit_answer(work, name))
        else:
            response = invoke_with_fallback(
                [
                    SystemMessage(content=with_profile(system_prompt)),
                    *compact_tool_history(work),
                ],
                tools=tools,
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
            trace = observability.current()
            if trace:
                trace.agent_event(name, time.time() - node_started, True)
            safe_print(f"\n[TRACE] {name} completed its task.")

        return {"work_messages": [response]}

    return node


def make_traced_tool_node(name: str, tools: list) -> Callable:
    tool_node = ToolNode(tools, messages_key="work_messages")

    def node(state: AgentState):
        started = time.time()
        result = tool_node.invoke(state)
        elapsed = time.time() - started
        # Cap each result before it enters the running history.
        for message in result["work_messages"]:
            if len(str(message.content)) > MAX_TOOL_RESULT_CHARS:
                message.content = _cap_tool_output(str(message.content))
        trace = observability.current()
        safe_print(f"\n[TRACE] {name} tools executed:")
        for message in result["work_messages"]:
            tool_name = getattr(message, "name", "unknown_tool")
            content = str(message.content)
            if trace:
                # ToolNode swallows exceptions into the message text.
                failed = content.lower().startswith(("error", "tool error"))
                trace.tool_event(name, tool_name, elapsed, not failed)
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


def deliver_message(
    question: str, answer: str, channel: str | None = None, webhook_env: str = ""
) -> bool:
    """Deliver a message through the given channel (email/telegram/whatsapp).
    Reusable by the workflow node and by the scheduled briefing runner.

    `webhook_env` routes a Discord message to a briefing-specific channel."""
    channel = (channel or DEFAULT_DELIVERY_CHANNEL).lower().strip()
    if channel == "telegram":
        return deliver_telegram(question, answer)
    if channel == "whatsapp":
        return deliver_whatsapp(question, answer)
    if channel == "discord":
        return deliver_discord(question, answer, webhook_env)
    return deliver_email(question, answer)


def deliver_discord(question: str, answer: str, webhook_env: str = "") -> bool:
    _, body = format_for_channel(question, answer, "chat")
    try:
        result = send_discord_message.invoke({"text": body, "webhook_env": webhook_env})
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
def _reset_work_messages(state: AgentState, task: str, step_results: list | None = None) -> list:
    """Clear the previous step's scratch messages and seed the new task.

    Earlier steps' findings are carried forward as context so a later specialist can
    build on them instead of starting blind (shared memory across the plan).
    """
    removals = [
        RemoveMessage(id=m.id)
        for m in state.get("work_messages", [])
        if getattr(m, "id", None) is not None
    ]

    content = task
    shared = format_shared_context(step_results or [])
    if shared:
        content = (
            f"{task}\n\n"
            "Findings from earlier agents on this request - build on these, do not "
            f"repeat their work:\n{shared}"
        )
    return [*removals, HumanMessage(content=content)]


def format_shared_context(step_results: list, max_chars: int = 3500) -> str:
    """Condense completed step results into context for the next agent."""
    if not step_results:
        return ""
    blocks = [
        f"[{entry['agent']}] {entry['result']}"
        for entry in step_results
        if entry.get("result")
    ]
    return _truncate_for_context("\n\n".join(blocks), max_chars)


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


def _section_name(line: str) -> str | None:
    lowered = line.lower()
    if lowered.startswith("section:"):
        return line.split(":", 1)[1].strip()
    if lowered.startswith("live updates:"):
        return line.split(":", 1)[1].strip() + " (live)"
    return None


def _parse_news_blocks(block: str) -> list[tuple[str, list[dict]]]:
    """Split one tool result into its sections.

    A single fetch now returns a global block AND a local one, so the header has
    to be recognised wherever it appears. Reading only the first line silently
    merged Nepal items into the global section - the local news was fetched and
    then vanished from the digest.
    """
    blocks: list[tuple[str, list[dict]]] = []
    section = "News"
    items: list[dict] = []
    current: dict = {}

    def close() -> None:
        nonlocal current
        if current:
            items.append(current)
            current = {}

    for raw in block.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue

        name = _section_name(stripped)
        if name is not None:
            close()
            if items or blocks or section != "News":
                blocks.append((section, items))
            section, items = name, []
            continue

        match = _NEWS_ITEM_START.match(stripped)
        if match:
            close()
            _absorb_news_field(current, match.group(1))
        else:
            _absorb_news_field(current, stripped)

    close()
    blocks.append((section, items))
    return [(name, found) for name, found in blocks if found]


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
        for section, items in _parse_news_blocks(str(message.content)):
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


def run_agent(
    question: str,
    deliver: bool = True,
    channel: str | None = None,
    source: str = "cli",
    session_id: str = "cli",
):
    observability.start_run(question, source)
    try:
        result = app.invoke(
            {
                "messages": [("user", question)],
                "work_messages": [],
                "plan": [],
                "step_index": 0,
                "step_results": [],
                "awaiting_result": False,
                "current_agent": "",
                "session_id": session_id,
                "delivery_channel": (channel or DEFAULT_DELIVERY_CHANNEL),
                "auto_deliver": deliver,
                "email_sent": False,
                "delivered": False,
            },
            config={"recursion_limit": 50},
        )
    except Exception as exc:
        observability.finish_run(error=str(exc))
        raise

    final_answer = str(result["messages"][-1].content)
    observability.finish_run(answer=final_answer)
    memory.save_turn(session_id, question, final_answer)
    return result


def answer_only(question: str, channel: str | None = None) -> str:
    """Run the workflow but skip delivery; return the composed answer text.

    Used by the scheduled briefing runner to gather several sections and deliver
    them as a single message.
    """
    result = run_agent(question, deliver=False, channel=channel)
    return str(result["messages"][-1].content)


def run_and_answer(
    question: str,
    source: str = "cli",
    channel: str | None = None,
    session_id: str | None = None,
) -> str:
    """answer_only, but tags the trace and keeps per-user conversation memory."""
    result = run_agent(
        question,
        deliver=False,
        channel=channel,
        source=source,
        session_id=session_id or source,
    )
    return str(result["messages"][-1].content)


def analyze_image_message(image_url: str, caption: str = "") -> str:
    """Analyze an image (path or URL) directly via the vision tools.

    Called by chat bots when a message includes an image attachment. Picks chart
    analysis when the caption hints at a market chart, otherwise general vision.
    """
    lowered = (caption or "").lower()
    chart_terms = (
        "chart",
        "stock",
        "stocks",
        "crypto",
        "trading",
        "candle",
        "price",
        "ticker",
        "forex",
        "nepse",
        "support",
        "resistance",
    )
    if any(term in lowered for term in chart_terms):
        return str(analyze_chart.invoke({"image_source": image_url, "question": caption}))
    return str(describe_image.invoke({"image_source": image_url, "question": caption}))


# --------------------------------------------------------------------------- #
# Proactive delivery: scheduled briefings ("it delivers", not "I ask")
# --------------------------------------------------------------------------- #
# Each briefing is a set of sections. Every section is run through the full agent
# workflow (so the commander still routes to the right specialist), the answers are
# combined into one message, and delivered a single time to your channel.
BRIEFINGS = {
    "ai": {
        "title": "AI Morning Brief",
        "sections": [
            (
                "AI news",
                "Use fetch_ai_news for today's AI briefing. Keep the four angles "
                "as separate headings: model releases, benchmarks, tooling, "
                "industry. For any new model, say what it is, who made it, and "
                "what it claims to beat. For benchmarks, give the numbers and "
                "name the comparison. Say plainly when a claim is vendor-reported "
                "rather than independently verified. Skip funding and opinion "
                "pieces unless they change what a practitioner should use.",
            ),
        ],
    },
    "dev": {
        "title": "Dev Radar",
        "sections": [
            (
                "GitHub",
                "Use fetch_trending_repos for repositories gaining traction. For "
                "each: what it does in one line, its star count, and why it is "
                "worth a look or not. Skip anything that is a tutorial list, an "
                "awesome-list, or a wrapper with no substance.",
            ),
            (
                "Papers",
                "Use fetch_papers for recent work, and foundational_papers with "
                "count 2 for classics worth revisiting. For each recent paper: "
                "the claim in one sentence, the result that supports it, and who "
                "should care. Say plainly when a result is preliminary or on a "
                "single benchmark. Always include the arXiv link.",
            ),
        ],
    },
    "interview": {
        "title": "Daily Interview Practice",
        # Generated by the coach rather than the agent chain: it rotates a
        # syllabus and records what has been covered, which a per-run prompt
        # cannot do. Routed to its own channel when the webhook is set.
        "builder": "interview",
        "webhook_env": "DISCORD_INTERVIEW_WEBHOOK_URL",
        "sections": [],
    },
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
                "In Nepal",
                "Use search_jobs_nepal for up to 4 current openings in Nepal that "
                "match my resume. For each: company, role, location, why it fits, "
                "and the apply link. Say plainly if the local market has nothing "
                "close this week rather than padding with loose matches.",
            ),
            (
                "Remote, open worldwide",
                "Use search_jobs_remote_global for up to 4 roles genuinely open to "
                "someone in Nepal. For each: company, role, why it fits, the apply "
                "link, and the eligibility flag. Where a listing looks region-locked "
                "say so and do not count it as a match. Name the likely engagement "
                "route (contractor, EOR, or unclear) when the posting indicates it.",
            ),
        ],
    },
    "finance": {
        "title": "Markets - Global",
        "sections": [
            (
                "Global markets",
                "Give me a global markets read: major indices, the dollar, gold and "
                "oil, and any central bank or macro event that moved them. For each "
                "move say what caused it, not just the number. Close with one or two "
                "things to watch in the next 24 hours. No NEPSE here - that has its "
                "own briefing.",
            ),
        ],
    },
    "nepse": {
        "title": "NEPSE",
        "sections": [
            (
                "NEPSE today",
                "First call get_nepse_history to see what has already been recorded. "
                "Then use search_nepal_finance to find today's NEPSE index level, "
                "points change and turnover. If you find a real index level, call "
                "log_nepse_reading with exactly the numbers you read - never "
                "estimate one and never reuse a previous day's. If today's numbers "
                "are not published yet, say so and log nothing. Finish by describing "
                "what the recorded series shows: direction, the range, and whether "
                "today continues or breaks it. Describe the data - do not tell me to "
                "buy or sell.",
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

    if briefing.get("builder") == "interview":
        from src.interview_agent.coach import daily_set

        safe_print(f"\n[BRIEFING] Building 'interview' for {today}")
        practice = daily_set()
        return (
            f"{briefing['title']} - {today}\n\n"
            f"**{practice['area']}: {practice['topic']}**\n"
            f"_Topic {practice['covered']} of {practice['total']}_\n\n"
            f"{practice['body']}"
        )
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
    # Every briefing can have its own channel by convention: set
    # DISCORD_AI_WEBHOOK_URL, DISCORD_NEWS_WEBHOOK_URL and so on. Unset vars fall
    # back to the main channel, so this costs nothing until it is used.
    webhook_env = BRIEFINGS[name].get("webhook_env") or f"DISCORD_{name.upper()}_WEBHOOK_URL"
    delivered = deliver_message(BRIEFINGS[name]["title"], text, channel, webhook_env)
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
    parser.add_argument("--check-config", action="store_true", help="validate .env and exit")
    parser.add_argument("--stats", action="store_true", help="show recent run traces and exit")
    args = parser.parse_args()

    if args.stats:
        observability.print_summary()
    elif args.check_config:
        from src.config_check import report

        report(exit_on_error=True)
    elif args.test_delivery:
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
