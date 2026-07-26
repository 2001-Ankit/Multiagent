"""Startup configuration check.

Catches the common first-deploy mistakes (missing key, still-a-placeholder value,
delivery channel configured without its credentials) and says exactly what to fix,
instead of failing later with a confusing provider error.

Use it directly:
    uv run python -m src.config_check
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Values that mean "the user never filled this in".
_PLACEHOLDER_MARKERS = (
    "your_",
    "_here",
    "example@",
    "paste",
    "changeme",
    "xxx",
    "pick_any",
)

CHANNEL_REQUIREMENTS = {
    "email": ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "DELIVERY_EMAIL_TO"),
    "discord": ("DISCORD_WEBHOOK_URL",),
    "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
    "whatsapp": ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TO"),
}


def _value(name: str) -> str:
    return os.getenv(name, "").strip()


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _check_var(name: str, hint: str, problems: list[str]) -> bool:
    value = _value(name)
    if not value:
        problems.append(f"{name} is not set - {hint}")
        return False
    if _is_placeholder(value):
        problems.append(f"{name} still looks like a placeholder ({value[:24]!r}) - {hint}")
        return False
    return True


def check_config(require_bot: bool = False) -> tuple[list[str], list[str]]:
    """Validate configuration. Returns (errors, warnings).

    Errors mean the app cannot work. Warnings mean a capability is simply disabled.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. The brain LLM is mandatory.
    if not (_value("LLM_API_KEY") or _value("GROQ_API_KEY")):
        errors.append(
            "No LLM key found - set GROQ_API_KEY (or LLM_API_KEY for another "
            "OpenAI-compatible provider) in .env"
        )
    elif _is_placeholder(_value("LLM_API_KEY") or _value("GROQ_API_KEY")):
        errors.append("Your LLM key still looks like a placeholder - paste the real key")

    # 2. Delivery channel must have its credentials.
    channel = (_value("DELIVERY_CHANNEL") or "email").lower()
    if channel not in CHANNEL_REQUIREMENTS:
        errors.append(
            f"DELIVERY_CHANNEL={channel!r} is not supported - use one of: "
            + ", ".join(sorted(CHANNEL_REQUIREMENTS))
        )
    else:
        for name in CHANNEL_REQUIREMENTS[channel]:
            _check_var(name, f"required because DELIVERY_CHANNEL={channel}", errors)

    # 3. Discord bot token, only when running the bot.
    if require_bot:
        _check_var("DISCORD_BOT_TOKEN", "needed to run the Discord bot", errors)
        if not _value("DISCORD_ALLOWED_USER_ID"):
            warnings.append(
                "DISCORD_ALLOWED_USER_ID is not set - anyone in the server can use the bot"
            )

    # 4. Optional capabilities: warn so it's obvious what's off.
    if not _value("NVIDIA_API_KEY") or _is_placeholder(_value("NVIDIA_API_KEY")):
        warnings.append("NVIDIA_API_KEY not set - image/chart analysis (vision) is disabled")

    resume_dirs = [PROJECT_ROOT / "data" / "resume", PROJECT_ROOT / "src" / "resume"]
    has_resume = any(
        item.is_file()
        and item.suffix.lower() in {".pdf", ".txt", ".md"}
        and item.stem.lower() != "readme"
        for directory in resume_dirs
        if directory.exists()
        for item in directory.iterdir()
    )
    if not has_resume and not _value("RESUME_PATH"):
        warnings.append(
            "No resume found in data/resume/ or src/resume/ - job matching and resume "
            "tailoring will be limited"
        )

    if not (PROJECT_ROOT / "data" / "profile.md").exists() and not _value("USER_PROFILE"):
        warnings.append(
            "No data/profile.md or USER_PROFILE - answers will not be personalized"
        )

    schedule = _value("BRIEFING_SCHEDULE")
    if require_bot and not schedule:
        warnings.append(
            "BRIEFING_SCHEDULE is empty - automatic briefings are off "
            '(example: "07:30=daily,19:00=news")'
        )

    return errors, warnings


def report(require_bot: bool = False, exit_on_error: bool = False) -> bool:
    """Print the check results. Returns True when there are no errors."""
    errors, warnings = check_config(require_bot=require_bot)

    for warning in warnings:
        print(f"[config] WARNING: {warning}")

    if errors:
        print("\n[config] Configuration problems found:")
        for error in errors:
            print(f"  - {error}")
        print("\n[config] Fix these in your .env file (see .env.example), then retry.")
        if exit_on_error:
            sys.exit(1)
        return False

    print("[config] OK: required settings present.")
    return True


if __name__ == "__main__":
    report(require_bot="--bot" in sys.argv, exit_on_error=True)
