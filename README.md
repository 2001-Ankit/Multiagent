# Multi-agent workflow

## Architecture

A **CommanderAgent** acts as a planner/orchestrator. For each request it builds a
short ordered plan, assigning each step to one specialist, then dispatches the
steps, composes a single final answer, and hands it to the delivery agent.

Specialists:

- **search_agent** — general web/news/image/video/book research.
- **finance_agent** — markets, investing, stocks, forex, crypto, macro, NEPSE.
- **news_agent** — daily sectioned news briefing (finance, politics, sports with
  live scores, world/top stories, or any topics you name).
- **academic_agent** — US graduate study: matching professors/labs to a student's
  research interest, plus admission requirements, deadlines, tests, and funding.
- **job_finder_agent** — reads your resume, sources jobs (web + optional Indeed
  MCP), checks eligibility, tailors your resume per role, drafts outreach, and
  recommends where to apply with deadlines.
- **market_opportunity_agent** — finds business/startup opportunities: trends,
  market gaps, competitors, demand/funding signals, ranked with a validation step.
- **learning_agent** — compares your resume to a target role, finds the skill gaps,
  and builds a prioritized roadmap of free resources and portfolio projects.
- **scholarship_agent** — scholarships/fellowships you're eligible for by
  nationality/field/level, with eligibility, award, deadlines, and how to apply.
- **travel_agent** — visa requirements for your passport, cost of living, flights,
  and a step-by-step trip/relocation plan.
- **content_agent** — drafts ready-to-post LinkedIn posts, X threads, and
  newsletters in your voice, grounded in current facts and your background.
- **price_watch_agent** — checks stock/crypto/currency/product prices against a
  target and returns an ALERT/WATCH/NO-ACTION verdict (great with the `watch`
  briefing + scheduler).

Each plan step is logged with the specialist chosen and the reason, so you can see
how the commander allocated resources.

### Execution modes (swarm)

The commander also decides *how* the agents run, and logs its choice:

- **solo** — one specialist answers. Used for most requests, so simple questions
  don't pay the cost of a committee.
- **parallel** — several specialists attack the **same** question from different
  angles **at the same time**, then an aggregator merges them: where they agree
  (higher confidence), where they conflict, and one clear conclusion. This is the
  swarm / mixture-of-agents path — use it for open analytical questions ("find the
  market gap for X", "evaluate this opportunity").
- **sequential** — later steps need earlier output (research → write it up). Each
  step receives the previous steps' findings as shared context.

Fan-out is capped by `SWARM_MAX_WORKERS` (default 3). Parallel agents multiply
tokens-per-minute, so on a free provider tier expect rate-limit retries — they are
handled automatically, they just make the run slower.

### Token cost control

An agent re-sends its whole message history on every round, so accumulated tool
output — not the prompts — is what actually drains a daily quota. Left unchecked one
swarm query can cost ~70k tokens (most free tiers allow 100k/day). Four controls keep
that in check:

| Control | Effect |
|---|---|
| `MAX_TOOL_RESULT_CHARS` (1500) | caps each tool result before it enters context |
| `TOOL_HISTORY_KEEP_FULL` (2) | older results collapse to a stub — stops quadratic growth (~55% smaller histories) |
| `max_rounds` (4 per agent) | fewer accumulation steps |
| `MAX_SWARM_AGENTS` (3) | fewer parallel agents |

Plus a budget guard: once estimated usage passes `SWARM_BUDGET_FRACTION` of
`DAILY_TOKEN_BUDGET`, swarms automatically downgrade to a single agent so the rest of
the day still works.

```env
SWARM_MAX_WORKERS=3
MAX_SWARM_AGENTS=3
MAX_TOOL_RESULT_CHARS=1500
TOOL_HISTORY_KEEP_FULL=2
DAILY_TOKEN_BUDGET=100000
SWARM_BUDGET_FRACTION=0.6
```

Adding a specialist is a one-entry change in `SPECIALIST_ROUTES` in
`src/multi-agent_workflow.py` (prompt, tools, max tool rounds); the graph wires
its node, tool node, and edges automatically.

Run it:

```powershell
uv run python src/multi-agent_workflow.py

# Check your .env is complete before anything else
uv run python src/multi-agent_workflow.py --check-config
```

## From "I ask" to "it delivers" (proactive briefings)

The system can build and **push** briefings to you on a schedule instead of waiting
for you to ask. A briefing is a set of sections; each runs through the full agent
workflow, and the results are combined into one message and delivered once.

Built-in briefings: `daily` (news + markets watch + job matches), `news`, `jobs`.
Edit the `BRIEFINGS` dict in `src/multi-agent_workflow.py` to change them.

```powershell
# Send a test message to confirm delivery works
uv run python src/multi-agent_workflow.py --test-delivery --channel telegram

# Build + deliver a briefing now
uv run python src/multi-agent_workflow.py --briefing daily --channel telegram

# One-off request (delivered), or add --no-deliver to just print it
uv run python src/multi-agent_workflow.py --query "scholarships for Nepali students in CS"
```

### Schedule it (Windows Task Scheduler)

Run the daily briefing every morning at 7:30am:

```powershell
$action  = New-ScheduledTaskAction -Execute "uv" `
  -Argument "run python src/multi-agent_workflow.py --briefing daily --channel telegram" `
  -WorkingDirectory "e:\multi-agent"
$trigger = New-ScheduledTaskTrigger -Daily -At 7:30am
Register-ScheduledTask -TaskName "MultiAgentDailyBriefing" -Action $action -Trigger $trigger
```

On Linux/macOS the equivalent cron line is:

```cron
30 7 * * *  cd /path/to/multi-agent && uv run python src/multi-agent_workflow.py --briefing daily --channel telegram
```

## Telegram setup

So briefings arrive as a chat message:

1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts, and copy
   the **bot token** it gives you.
2. Send your new bot any message (e.g. "hi") so it can reply to you.
3. Get your chat id: open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and copy the
   number in `"chat":{"id": ... }`.
4. Put both in `.env` and set the default channel:

   ```env
   DELIVERY_CHANNEL=telegram
   TELEGRAM_BOT_TOKEN=123456:ABC-your-token
   TELEGRAM_CHAT_ID=123456789
   ```

5. Confirm: `uv run python src/multi-agent_workflow.py --test-delivery --channel telegram`
   — you should get a test message. Long messages are auto-split into 4096-char parts.

### Two-way Telegram bot (message it, it replies)

Beyond scheduled pushes, you can chat *with* the bot — send it a question and it
runs the agents and replies. It uses long polling (no public URL needed) and only
responds to your `TELEGRAM_CHAT_ID`, so strangers can't use it.

```powershell
uv run python src/telegram_bot.py
```

Then in Telegram, message your bot:

- Any question → routed to the right specialist and answered.
- `/daily`, `/news`, `/jobs`, `/watch` → run that briefing.
- `/help` → command list.

Leave it running (or start it on login) to have an always-available assistant. It
reuses the same delivery pipeline, so `DELIVERY_CHANNEL` can stay `telegram`.

## Daily news agent

Ask for a briefing (e.g. "give me today's news with finance, politics, sports")
and the news agent fetches recent headlines per section and returns a skimmable
digest, delivered through the delivery agent.

## Academic agent (US universities)

Ask about studying in the US (e.g. "find US professors working on graph neural
networks for a PhD, and the programs/deadlines"). The agent finds matching
professors/labs, explains the overlap with your interest, and lists admission
requirements, deadlines, tests, and funding — all with source URLs.

## Job finder agent

Ask something like "find me remote Python jobs I'm eligible for and tailor my
resume." The agent:

1. Reads your resume (see below).
2. Sources jobs across many boards with `search_jobs_web` (always on), and, if
   configured, `search_jobs_indeed` via an MCP server for extra reach.
3. Opens promising listings to read real requirements and deadlines.
4. **Checks eligibility for your country** (`CANDIDATE_COUNTRY`, default Nepal) —
   flags region-locked remote ("Remote, US only"), visa/work-authorization needs.
5. Tailors your resume bullets to each role and drafts a human outreach message.
6. Summarizes which companies to apply to first, with deadlines.

### Resume

Drop your resume into `data/resume/` **or** `src/resume/` as **PDF**, **TXT**, or
**Markdown**, or set `RESUME_PATH` in `.env`. PDFs are parsed with `pdfplumber`.
The newest supported file wins. Resume files are gitignored for privacy.

### Indeed via MCP (optional)

Web search works with no setup. For extra reach you can point the agent at a
runnable Indeed MCP server (stdio or HTTP) in `.env`:

```env
# pick ONE transport
INDEED_MCP_COMMAND=npx -y your-indeed-mcp-server
# or
INDEED_MCP_URL=https://your-indeed-mcp-host/mcp
INDEED_MCP_TOKEN=your_token
```

Note: the claude.ai-hosted Indeed connector authenticates through claude.ai's OAuth
and cannot be used by this standalone app; supply your own runnable MCP endpoint.
If nothing is configured, the agent falls back to web search automatically.

## Finance agent

The workflow includes a finance agent for stocks, forex, crypto, investment
research, financial benefits, and Nepal/NEPSE finance questions. It can give
specific, fact-based opinions and suggestions while keeping clear that outputs
are research, not personalized financial advice.

Structured market data uses **Yahoo Finance (`yfinance`) - no API key required**.
Covered: live quotes, company fundamentals/overview, daily history with
trend/volume signals, financials, analyst view, forex, crypto, **commodities**
(gold, oil, copper, gas, grains...), and a one-glance **global market snapshot**
(indices, gold, oil, the dollar, 10Y yield, VIX, Bitcoin) for macro awareness.

Macro, political, inflation, interest-rate, currency, and geopolitical context uses
web/news research. Nepal-specific coverage uses `search_nepal_finance`.

No finance API key is needed anymore (Alpha Vantage has been removed).

Finance answers should be treated as research and education only, not
personalized financial advice.

## Gmail delivery tool

The delivery agent exposes a Gmail API based email tool at
`src.delivery_agent.tools.send_email`.

Setup:

1. Enable the Gmail API in a Google Cloud project.
2. Configure the OAuth consent screen.
3. Create an OAuth client ID with application type `Desktop app`.
4. Download the OAuth client JSON as `credentials.json` in the project root.
5. Install dependencies with `uv sync`.
6. Run the email tool once from a local terminal so the OAuth browser flow can
   create `token.json`.

Both `credentials.json` and `token.json` are ignored by git. You can override
their locations with:

```env
GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
```

To use it as a LangChain tool, import and bind it to an agent:

```python
from langchain_openai import ChatOpenAI

from src.delivery_agent.tools import send_email

llm = ChatOpenAI(...)
delivery_llm = llm.bind_tools([send_email])
```

## WhatsApp delivery (Cloud API)

If Telegram is slow/blocked on your network (common in Nepal), WhatsApp's Cloud API
is a fast alternative for **outbound** delivery.

1. At [developers.facebook.com](https://developers.facebook.com) create an app →
   add the **WhatsApp** product.
2. Copy the temporary **access token** and **phone number ID** from the WhatsApp
   setup page; add your own number as a verified recipient.
3. Put them in `.env` and set the channel:

   ```env
   DELIVERY_CHANNEL=whatsapp
   WHATSAPP_ACCESS_TOKEN=EAAG...
   WHATSAPP_PHONE_NUMBER_ID=123456789012345
   WHATSAPP_TO=9779800000000
   ```

4. Test: `uv run python src/multi-agent_workflow.py --test-delivery --channel whatsapp`

Notes: free-form messages only reach you inside a 24-hour window after you message
the business number (Meta policy); outside that you need an approved template.

### Two-way WhatsApp bot (webhook + ngrok)

WhatsApp has no polling — Meta pushes messages to a public URL. For a personal bot,
run the webhook server locally and expose it with ngrok. Only `WHATSAPP_TO` is
handled, so nobody else can drive your agents.

1. Add to `.env`: `WHATSAPP_VERIFY_TOKEN=<any secret string>` (plus the WhatsApp
   Cloud API vars above).
2. Start the bot: `uv run python src/whatsapp_bot.py`
3. In another terminal expose it: `ngrok http 8000` → copy the `https://...` URL.
4. In the Meta app → **WhatsApp → Configuration → Edit** webhook:
   - Callback URL: `https://<your-ngrok>.ngrok-free.app/webhook`
   - Verify token: the same `WHATSAPP_VERIFY_TOKEN`
   - Click **Verify and save**, then **Subscribe** to the `messages` field.
5. Message your WhatsApp test number — the bot runs the agents and replies. Commands:
   `/daily` `/news` `/jobs` `/watch` `/help`.

Note: the free test setup only talks to numbers you pre-register (up to 5). A bot
anyone can message needs a verified WhatsApp Business number.

## Discord (recommended if Telegram is throttled / no WhatsApp business account)

Discord is fast from most networks and needs no business verification. It gives you
both **delivery** (via a channel webhook) and a **two-way bot** (message it, it
replies).

### Delivery (webhook, no bot needed)

1. In your Discord server: **Channel settings → Integrations → Webhooks → New
   Webhook → Copy URL**.
2. Put it in `.env` and set the channel:

   ```env
   DELIVERY_CHANNEL=discord
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/....
   ```

3. Test: `uv run python src/multi-agent_workflow.py --test-delivery --channel discord`

### Two-way bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
   → **New Application** → **Bot** → **Reset Token** and copy it.
2. Under the bot settings, enable **Message Content Intent**.
3. **OAuth2 → URL Generator**: scope `bot`, permissions *Send Messages* + *Read
   Message History*. Open the generated URL to invite the bot to your server.
4. In `.env`:

   ```env
   DISCORD_BOT_TOKEN=your_bot_token
   DISCORD_ALLOWED_USER_ID=your_discord_user_id
   ```

   (Your user id: enable Developer Mode in Discord, right-click your name → Copy ID.)
5. Run: `uv run python src/discord_bot.py` — then message the bot in your server.
   Commands: `/daily` `/news` `/jobs` `/watch` `/help`.

## Running it 24/7 on your own PC (no card, no signup)

Every cloud provider now requires a payment method for verification, so the simplest
always-on option is your own machine. The bot runs whenever the PC is on, restarts
itself if it crashes, and starts automatically when you log in.

```powershell
# 1. Confirm your configuration is complete
uv run python src/multi-agent_workflow.py --check-config

# 2. Enable automatic briefings in .env (optional)
#    BRIEFING_SCHEDULE=07:30=daily,19:00=news
#    TIMEZONE=Asia/Kathmandu

# 3. Install auto-start (registers a Scheduled Task, runs at log on)
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1

# 4. Start it now without rebooting
Start-ScheduledTask -TaskName MultiAgentDiscordBot

# 5. Watch the log
Get-Content logs\bot.log -Wait -Tail 30
```

To run it in the foreground instead (handy while testing), skip the task and use the
supervisor directly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_bot.ps1
```

Remove auto-start with `powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1`.

**What this gives you**

- `scripts\run_bot.ps1` restarts the bot 15s after any crash, appending to
  `logs\bot.log` (rotated at ~5 MB).
- The Scheduled Task has no execution time limit, so Windows won't kill it.
- The bot holds a **single-instance lock** (a loopback port), so a second copy exits
  immediately instead of replying to every message twice. Override with
  `BOT_LOCK_PORT` if you ever want two bots on purpose.

**Limitation:** the bot is offline while the PC is asleep or off. For true 24/7,
either leave the machine on (disable sleep) or move to a cloud VM later — the
`Dockerfile` below deploys the same code unchanged.

## Hosting it 24/7 on a cloud VM (Oracle Cloud Always Free)

Note: Oracle asks for a card for **identity verification only** (Always Free
resources are never charged), and international cards from some countries can fail
that check. If you're a student, **GitHub Student Pack → Azure for Students** gives
credit with no card required.



The Discord bot holds a persistent gateway connection, so it needs an always-on
process (serverless platforms won't work). This repo ships a `Dockerfile` and
`docker-compose.yml`, and the bot runs its **own scheduler**, so a single deployment
gives you chat *and* automatic briefings — no cron or Task Scheduler needed.

### 1. Create the free VM

1. Sign up at [cloud.oracle.com](https://cloud.oracle.com) (card needed for identity
   verification only — pick **Always Free** resources).
2. **Compute → Instances → Create Instance.**
3. Image: **Ubuntu 22.04**. Shape: **VM.Standard.A1.Flex** (Ampere ARM) — set
   **1–2 OCPU / 6–12 GB RAM**, all within Always Free.
4. Save the **SSH private key** when prompted, then create the instance and copy its
   public IP.

### 2. Connect and install Docker

```bash
ssh -i /path/to/your-key.key ubuntu@YOUR_PUBLIC_IP

sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker
```

### 3. Get the code onto the VM

Use a **private** GitHub repo (never public — it would expose your work, and any
committed secret gets scraped within minutes):

```bash
git clone https://github.com/<you>/<your-private-repo>.git multi-agent
cd multi-agent
```

### 4. Add the files that are gitignored

`.env`, your resume, and `data/profile.md` are deliberately not in git, so copy them
up from your PC (run these **locally**, not on the VM):

```powershell
scp -i C:\path\to\key.key .env ubuntu@YOUR_PUBLIC_IP:~/multi-agent/.env
scp -i C:\path\to\key.key data\profile.md ubuntu@YOUR_PUBLIC_IP:~/multi-agent/data/profile.md
scp -i C:\path\to\key.key src\resume\AnkitResume.pdf ubuntu@YOUR_PUBLIC_IP:~/multi-agent/src/resume/
```

### 5. Turn on the scheduler, then start

In `.env` on the VM, enable automatic briefings (times are in `TIMEZONE`):

```env
BRIEFING_SCHEDULE=07:30=daily,19:00=news
TIMEZONE=Asia/Kathmandu
DELIVERY_CHANNEL=discord
```

Verify the configuration before starting (catches a missing key, a value you forgot
to replace, or a delivery channel without its credentials):

```bash
docker compose run --rm bot uv run python -m src.config_check --bot
```

```bash
docker compose up -d --build      # build and run in the background
docker compose logs -f            # watch it boot (Ctrl+C to stop watching)
```

You should see `logged in as Mark`, the brain model, and a `[scheduler] next 'daily'
at ...` line. `restart: unless-stopped` means it survives crashes and VM reboots.

### Everyday commands

```bash
docker compose logs -f            # tail logs
docker compose restart            # restart the bot
docker compose down               # stop it
git pull && docker compose up -d --build   # deploy an update
```

Now you can message the bot from your phone any time — your PC can be off.

## Blog + content pipeline

One topic becomes a blog post, social posts and a video script — then you review and
publish. Nothing goes live without your approval.

### `/content` — the full pack

`/content <topic>` runs a **fixed** pipeline (it does not ask the planner to guess):

```
topic -> research once (research_for_content + find_keywords_and_questions)
      -> blog post      (ghostwriter prompt)   -> saved as a draft
      -> LinkedIn post + X thread + Short script  (one repurposing call)
```

Researching once and reusing the findings keeps every output consistent with the
others and keeps the run affordable.

```powershell
uv run python -m src.content_pipeline "why Nepali students should learn Python"
```

### Publishing by pull request (recommended)

The blog itself is a separate **Astro** app in [`blog-site/`](blog-site/) — push it
to its own repo. When `GITHUB_TOKEN` and `BLOG_REPO` are set, `/content` and `/blog`
stop writing local files and instead:

```
/content <topic>
  -> research + write
  -> create branch  post/<date>-<slug>  in the blog repo
  -> commit the Markdown post
  -> open a pull request  (social copy + video script go in the PR description)
  -> reply in Discord with the PR link
```

You review the **diff on GitHub**, edit if you want, and merge — GitHub Actions then
builds and deploys. A PR is a proposal, so nothing can go live on its own.

Setup:

1. Push `blog-site/` to a new repo, then **Settings → Pages → Source: GitHub Actions**.
2. Create a **fine-grained PAT** scoped to that repo with
   **Contents: read/write** and **Pull requests: read/write**.
3. Add it to `.env`:

   ```env
   GITHUB_TOKEN=github_pat_...
   BLOG_REPO=your-name/your-blog-repo
   BLOG_POSTS_PATH=src/content/blog
   BLOG_BASE_BRANCH=main
   ```

`BLOG_POSTS_PATH` is what makes this portable — point it at `content/posts` for Hugo
or `_posts` for Jekyll and the same flow works.

### Review and publish locally (fallback)

Used when no blog repo is configured; posts go to the built-in Python site instead.

In Discord: `/content <topic>` or `/blog <topic>` → `/drafts` → `/publish <id>`.

From the terminal:

```powershell
uv run python -m src.blog.writer "your topic"        # write a draft
uv run python -m src.blog.publish_cli list           # see drafts
uv run python -m src.blog.publish_cli show <slug>    # read it
uv run python -m src.blog.publish_cli publish <slug> # publish + rebuild site
uv run python -m src.blog.publish_cli build          # rebuild only
```

Drafts live in `data/blog/drafts/`, published posts in `data/blog/posts/` — plain
Markdown with frontmatter, so they stay readable and portable.

### The site

`site/` is generated by a small Python builder: clean HTML with inlined CSS (no build
step, no external requests), light/dark, responsive, plus `rss.xml` and `sitemap.xml`.

Host it free on **GitHub Pages** (no card required):

1. Push the repo, then in GitHub go to **Settings → Pages**.
2. Source: **Deploy from a branch** → branch `main`, folder **`/site`** → Save.
3. Your site appears at `https://<user>.github.io/<repo>/`.
4. Set `BLOG_URL` in `.env` to that address so RSS and sitemap use absolute links.

```env
BLOG_TITLE=Ankit Rai
BLOG_TAGLINE=Notes on tech, markets, and studying abroad
BLOG_URL=https://2001-ankit.github.io/Multiagent
```

Deploying is an explicit step — publishing only writes files locally:

```powershell
git add site data/blog && git commit -m "new post" && git push
```

> **Publish deliberately.** Google's *scaled content abuse* policy targets
> mass-produced AI articles, and a site of unreviewed daily AI posts can be
> deindexed. Fewer, genuinely useful posts with your own perspective beat volume.

## Tests

```powershell
uv run pytest            # ~12 seconds, no network or API calls
uv run pytest -v         # per-test names
```

91 tests cover the logic that is easy to break and expensive to debug in production:

| File | Covers |
|---|---|
| `test_planning.py` | plan parsing, solo/parallel/sequential modes, agent selectivity (vision dropped without an image), keyword routing |
| `test_resilience.py` | error classification (daily vs per-minute limits), fallback chain integrity, tool-output caps, history compaction, budget guard |
| `test_memory.py` | thread turns, session isolation, truncation, facts, path-traversal safety |
| `test_output_and_tools.py` | news digest (headlines keep their URLs), delivery formatting, per-platform chunk limits, search caching, config validation, graph integrity |

They are deterministic and offline — no LLM calls, so they cost no quota.

## Observability (built in, no signup)

Every request is traced to `logs/runs.jsonl` — the mode the commander chose, each
agent's runtime, every tool call and failure, total duration, and the final answer.
No account, no external service, works offline.

```powershell
uv run python src/multi-agent_workflow.py --stats   # summary of recent runs
uv run python -m src.observability --last           # full JSON of the last run
```

The summary shows where time actually goes and what breaks:

```
time                 mode          secs  tools  fail  query
2026-07-29T22:47:46  parallel     119.7     12     0  Should I invest in gold right now...

Slowest agents (avg seconds):
  market_opportunity_agent       84.9s  (1 runs)
  news_agent                     57.9s  (1 runs)
  critic                         12.7s  (1 runs)
```

Disable with `RUN_TRACING=false`.

### Optional hosted tracing

If you later want a full trace UI, these plug into LangChain/LangGraph:

- **Langfuse** — open source, self-hostable for free, or a free cloud tier.
- **Arize Phoenix** — fully local, no account, OpenTelemetry-based.
- **LangSmith** — deepest LangGraph integration (just env vars, no code), but the
  free tier is limited and it becomes paid past that:

  ```env
  LANGSMITH_TRACING=true
  LANGSMITH_API_KEY=ls__your_key
  LANGSMITH_PROJECT=multi-agent
  ```

### Critic pass

In `parallel` mode, after the aggregator merges the swarm, a **CriticAgent** reviews
the draft against the raw findings — removing unsupported claims, surfacing
contradictions the merge glossed over, restoring dropped findings, and adding missing
source URLs. It costs one extra LLM call (far cheaper than multi-round debate) and
falls back to the draft if anything goes wrong.

```env
ENABLE_CRITIC=true
```

## Conversation memory

The bot remembers your recent thread, so follow-ups work:

```
you:  Name 3 programming languages good for beginners
bot:  Python, JavaScript, Ruby...
you:  Why is the second one good for beginners?     <- resolves to JavaScript
```

Two layers, both stored under `data/memory/` (gitignored):

- **Thread memory** — the last few turns per user, kept per Discord user id.
- **Facts** — durable things you ask it to remember, injected into every prompt.

```
/remember I hold NABIL bank shares
/memory      show what is stored
/forget      clear the recent conversation
```

It is deliberately cheap: history is truncated and sent **only to the planner**,
which rewrites a follow-up into a self-contained task before any specialist runs
(~300 tokens per request, not per agent).

```env
ENABLE_MEMORY=true
MEMORY_MAX_TURNS=4
MEMORY_MAX_ANSWER_CHARS=500
```

## Making the agents smarter

- **User profile** — `data/profile.md` (or `USER_PROFILE` in `.env`) is injected into
  every agent so answers stay personalized to you without re-explaining yourself.
- **Model** — the single biggest lever. Defaults to `llama-3.3-70b-versatile`, which
  has reliable tool-calling (avoid `gpt-oss-*` on Groq for the agents; they
  intermittently emit malformed tool calls).

### Model fallback (never dead-end on a rate limit)

Provider quotas are **per model**, so when the primary is exhausted for the day the
next model still has budget. The chain is tried in order and switches automatically:

```
llama-3.3-70b-versatile (Groq)
  -> llama-3.1-8b-instant (Groq)
  -> openai/gpt-oss-120b (Groq)
  -> moonshotai/kimi-k2.6 (NVIDIA)   # only if NVIDIA_API_KEY is set
```

```env
LLM_FALLBACK_MODELS=llama-3.1-8b-instant,openai/gpt-oss-120b
LLM_FALLBACK_NVIDIA_MODEL=moonshotai/kimi-k2.6
```

Errors are classified so the response is appropriate:

| Error | Behaviour |
|---|---|
| Per-**minute** limit (TPM) | wait and retry the same model (it will clear) |
| Per-**day** limit (TPD) | skip retries, switch model immediately |
| Malformed tool call | quick retry |
| Bad key / unknown model | switch provider |

Adding a second provider (NVIDIA) gives a completely separate quota pool, which is
the most effective way to stop hitting daily caps.

**Verify a fallback model before adding it.** It must be reachable by your account
*and* support tool calling, otherwise agents fall back to dumping raw tool output.
Checked on this project: `moonshotai/kimi-k2.6` returns 404, `kimi-k2-instruct`
returns 410, and `z-ai/glm-5.2` times out — `nvidia/llama-3.3-nemotron-super-49b-v1.5`
works with tools and is the default.

### Search resilience

A swarm can fire dozens of searches a minute, which DuckDuckGo throttles. All search
tools go through `src/search_core.py`, which adds a global throttle between outbound
requests, retries with backoff, and a shared short-lived cache so parallel agents
don't repeat each other's queries.

```env
SEARCH_MIN_INTERVAL=1.2   # seconds between real outbound searches
SEARCH_MAX_RETRIES=3
SEARCH_CACHE_TTL=900      # reuse identical queries for 15 minutes
```

### Agent selectivity

The planner is told to add an agent only when it contributes something the others
cannot, and a hard filter enforces it: an agent whose required input is missing is
dropped (e.g. `vision_agent` when the request contains no image), and plans are
capped at `MAX_SWARM_AGENTS` (default 4).

## Gmail MCP server

The same Gmail send capability is also available as an MCP server:

```powershell
uv run python -m src.delivery_agent.mcp_server
```

Register that command in any MCP-compatible host. The exposed MCP tool is named
`send_email` and accepts `to`, `subject`, `body`, `cc`, and `bcc`.
