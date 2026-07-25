from langchain.tools import tool

from src.vision_agent.nvidia_vlm import analyze_image

CHART_PROMPT = (
    "You are a market chart analyst. The image is a price chart for a stock, ETF, "
    "index, crypto, forex pair, or commodity. Analyze it carefully:\n"
    "- Identify the asset/ticker and timeframe if visible.\n"
    "- Describe the trend (up/down/sideways) and its strength.\n"
    "- Call out notable support and resistance levels or price zones you can see.\n"
    "- Name any chart patterns (e.g. breakout, head & shoulders, flag, double top) "
    "and candlestick/momentum signals if visible.\n"
    "- Note volume behavior if shown.\n"
    "Then give a clear, evidence-based read: likely scenarios and what to watch. "
    "Be explicit this is chart-reading, not financial advice, and never guarantee an "
    "outcome. Only describe what is actually visible in the image; do not invent "
    "numbers you cannot see."
)


@tool
def analyze_chart(image_source: str, question: str = "") -> str:
    """Analyze a stock/crypto/forex/index price chart screenshot (path or URL).

    Reads trend, support/resistance, patterns, and momentum from the chart image and
    gives an evidence-based technical read. Works for any market, not just crypto.
    """
    prompt = CHART_PROMPT
    if question.strip():
        prompt += f"\n\nAlso answer the user's question: {question.strip()}"
    return analyze_image(image_source, prompt, max_tokens=1200)


@tool
def describe_image(image_source: str, question: str = "") -> str:
    """Describe an image and extract any visible text (OCR), given a path or URL.

    Use for general images, screenshots, documents, or photos when it is not a
    market chart.
    """
    prompt = (
        question.strip()
        or "Describe this image in detail and transcribe any text visible in it."
    )
    return analyze_image(image_source, prompt, max_tokens=1024)
