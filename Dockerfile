# Runs the always-on Discord bot (chat + built-in briefing scheduler).
# Works on x86_64 and ARM64 (Oracle Cloud Always Free is ARM).
FROM python:3.12-slim

# tzdata is required for zoneinfo (Asia/Kathmandu scheduling).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first so code changes don't invalidate the dependency layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

CMD ["uv", "run", "python", "src/discord_bot.py"]
