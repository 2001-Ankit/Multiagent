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

## Making the agents smarter

- **User profile** — `data/profile.md` (or `USER_PROFILE` in `.env`) is injected into
  every agent so answers stay personalized to you without re-explaining yourself.
- **Model** — the single biggest lever. `GROQ_MODEL` defaults to a small 20B model;
  switch to `openai/gpt-oss-120b` or `llama-3.3-70b-versatile` for noticeably better
  reasoning and routing.

## Gmail MCP server

The same Gmail send capability is also available as an MCP server:

```powershell
uv run python -m src.delivery_agent.mcp_server
```

Register that command in any MCP-compatible host. The exposed MCP tool is named
`send_email` and accepts `to`, `subject`, `body`, `cc`, and `bcc`.
