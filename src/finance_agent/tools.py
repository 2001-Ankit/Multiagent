import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
ALPHA_VANTAGE_DOCS_URL = "https://www.alphavantage.co/documentation/"
MAX_FIELD_LENGTH = 500


@tool
def get_stock_quote(symbol: str) -> str:
    """Look up the latest available stock or ETF quote for a market symbol."""
    data = _alpha_vantage_query({"function": "GLOBAL_QUOTE", "symbol": symbol})
    if isinstance(data, str):
        return data

    quote = data.get("Global Quote") or {}
    if not quote:
        return _format_provider_empty("Stock quote", symbol, data)

    fields = {
        "Symbol": quote.get("01. symbol"),
        "Price": quote.get("05. price"),
        "Change": quote.get("09. change"),
        "Change Percent": quote.get("10. change percent"),
        "Previous Close": quote.get("08. previous close"),
        "Open": quote.get("02. open"),
        "High": quote.get("03. high"),
        "Low": quote.get("04. low"),
        "Volume": quote.get("06. volume"),
        "Latest Trading Day": quote.get("07. latest trading day"),
    }
    return _format_fields(
        title="Stock quote",
        identifier=symbol,
        fields=fields,
        source=ALPHA_VANTAGE_DOCS_URL,
    )


@tool
def get_company_overview(symbol: str) -> str:
    """Look up company overview and fundamental summary data for a symbol."""
    data = _alpha_vantage_query({"function": "OVERVIEW", "symbol": symbol})
    if isinstance(data, str):
        return data
    if not data or "Symbol" not in data:
        return _format_provider_empty("Company overview", symbol, data)

    wanted_fields = (
        "Symbol",
        "Name",
        "AssetType",
        "Exchange",
        "Currency",
        "Country",
        "Sector",
        "Industry",
        "MarketCapitalization",
        "PERatio",
        "PEGRatio",
        "DividendYield",
        "ProfitMargin",
        "QuarterlyEarningsGrowthYOY",
        "QuarterlyRevenueGrowthYOY",
        "AnalystTargetPrice",
        "52WeekHigh",
        "52WeekLow",
    )
    fields = {field: data.get(field) for field in wanted_fields}
    return _format_fields(
        title="Company overview",
        identifier=symbol,
        fields=fields,
        source=ALPHA_VANTAGE_DOCS_URL,
    )


@tool
def get_stock_history(symbol: str, days: int = 30) -> str:
    """Look up recent daily stock history for trend, volume, and price-action analysis."""
    safe_days = max(5, min(int(days), 100))
    data = _alpha_vantage_query(
        {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "compact",
        }
    )
    if isinstance(data, str):
        return data

    series = data.get("Time Series (Daily)") or {}
    if not series:
        return _format_provider_empty("Stock history", symbol, data)

    rows = []
    for date in sorted(series.keys(), reverse=True)[:safe_days]:
        day = series[date]
        rows.append(
            {
                "date": date,
                "open": _to_float(day.get("1. open")),
                "high": _to_float(day.get("2. high")),
                "low": _to_float(day.get("3. low")),
                "close": _to_float(day.get("4. close")),
                "volume": _to_float(day.get("5. volume")),
            }
        )

    if not rows:
        return _format_provider_empty("Stock history", symbol, data)

    latest = rows[0]
    oldest = rows[-1]
    closes = [row["close"] for row in rows if row["close"] is not None]
    volumes = [row["volume"] for row in rows if row["volume"] is not None]
    highs = [row["high"] for row in rows if row["high"] is not None]
    lows = [row["low"] for row in rows if row["low"] is not None]

    close_change = None
    if latest["close"] and oldest["close"]:
        close_change = ((latest["close"] - oldest["close"]) / oldest["close"]) * 100

    recent_volume = _average(volumes[:5])
    prior_volume = _average(volumes[5:20])
    volume_signal = None
    if recent_volume and prior_volume:
        volume_signal = ((recent_volume - prior_volume) / prior_volume) * 100

    fields = {
        "Symbol": symbol,
        "Window Days": len(rows),
        "Latest Date": latest["date"],
        "Latest Close": _format_number(latest["close"]),
        "Window Change Percent": _format_percent(close_change),
        "Window High": _format_number(max(highs) if highs else None),
        "Window Low": _format_number(min(lows) if lows else None),
        "Average Recent Volume 5D": _format_number(recent_volume),
        "Average Prior Volume": _format_number(prior_volume),
        "Recent Volume Change Percent": _format_percent(volume_signal),
    }
    return _format_fields(
        title="Stock history and demand/supply snapshot",
        identifier=symbol,
        fields=fields,
        source=ALPHA_VANTAGE_DOCS_URL,
    )


@tool
def get_forex_rate(from_currency: str, to_currency: str) -> str:
    """Look up the latest available exchange rate between two currencies."""
    data = _alpha_vantage_query(
        {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": from_currency,
            "to_currency": to_currency,
        }
    )
    if isinstance(data, str):
        return data

    rate = data.get("Realtime Currency Exchange Rate") or {}
    if not rate:
        pair = f"{from_currency}/{to_currency}"
        return _format_provider_empty("Forex rate", pair, data)

    fields = {
        "From": rate.get("1. From_Currency Code"),
        "From Name": rate.get("2. From_Currency Name"),
        "To": rate.get("3. To_Currency Code"),
        "To Name": rate.get("4. To_Currency Name"),
        "Exchange Rate": rate.get("5. Exchange Rate"),
        "Last Refreshed": rate.get("6. Last Refreshed"),
        "Time Zone": rate.get("7. Time Zone"),
        "Bid Price": rate.get("8. Bid Price"),
        "Ask Price": rate.get("9. Ask Price"),
    }
    return _format_fields(
        title="Forex rate",
        identifier=f"{from_currency}/{to_currency}",
        fields=fields,
        source=ALPHA_VANTAGE_DOCS_URL,
    )


@tool
def get_crypto_rate(symbol: str, market: str = "USD") -> str:
    """Look up the latest available cryptocurrency exchange rate."""
    data = _alpha_vantage_query(
        {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": symbol,
            "to_currency": market,
        }
    )
    if isinstance(data, str):
        return data

    rate = data.get("Realtime Currency Exchange Rate") or {}
    if not rate:
        pair = f"{symbol}/{market}"
        return _format_provider_empty("Crypto rate", pair, data)

    fields = {
        "From": rate.get("1. From_Currency Code"),
        "From Name": rate.get("2. From_Currency Name"),
        "To": rate.get("3. To_Currency Code"),
        "To Name": rate.get("4. To_Currency Name"),
        "Exchange Rate": rate.get("5. Exchange Rate"),
        "Last Refreshed": rate.get("6. Last Refreshed"),
        "Time Zone": rate.get("7. Time Zone"),
        "Bid Price": rate.get("8. Bid Price"),
        "Ask Price": rate.get("9. Ask Price"),
    }
    return _format_fields(
        title="Crypto rate",
        identifier=f"{symbol}/{market}",
        fields=fields,
        source=ALPHA_VANTAGE_DOCS_URL,
    )


@tool
def search_finance_news(query: str) -> str:
    """Search recent finance news and return article summaries, URLs, dates, and sources."""
    finance_query = f"{query} finance market investment news"
    try:
        results = DDGS().news(
            query=finance_query,
            region="us-en",
            safesearch="off",
            timelimit="m",
            page=1,
            max_results=4,
            backend="auto",
        )
    except DDGSException as exc:
        return _format_search_error(finance_query, "Finance news", exc)

    return _format_search_results(
        query=finance_query,
        result_type="Finance news",
        results=results,
        fields=("date", "title", "body", "url", "source"),
    )


@tool
def search_macro_finance_context(query: str) -> str:
    """Search macro, political, geopolitical, inflation, and central-bank context for finance analysis."""
    macro_query = (
        f"{query} politics geopolitics inflation central bank interest rates "
        "oil currency supply chain market impact finance"
    )
    try:
        web_results = DDGS().text(query=macro_query, max_results=3)
        news_results = DDGS().news(
            query=macro_query,
            region="us-en",
            safesearch="off",
            timelimit="m",
            page=1,
            max_results=4,
            backend="auto",
        )
    except DDGSException as exc:
        return _format_search_error(macro_query, "Macro finance context", exc)

    sections = [
        _format_search_results(
            query=macro_query,
            result_type="Macro finance web context",
            results=web_results,
            fields=("title", "body", "href"),
        ),
        _format_search_results(
            query=macro_query,
            result_type="Macro finance news context",
            results=news_results,
            fields=("date", "title", "body", "url", "source"),
        ),
    ]
    return "\n\n".join(sections)


@tool
def search_nepal_finance(query: str) -> str:
    """Search Nepal, NEPSE, NRB, and Nepal finance sources through web/news search."""
    nepal_query = f"{query} Nepal NEPSE NRB finance market"
    try:
        web_results = DDGS().text(query=nepal_query, max_results=3)
        news_results = DDGS().news(
            query=nepal_query,
            region="wt-wt",
            safesearch="off",
            timelimit="m",
            page=1,
            max_results=3,
            backend="auto",
        )
    except DDGSException as exc:
        return _format_search_error(nepal_query, "Nepal finance research", exc)

    sections = [
        _format_search_results(
            query=nepal_query,
            result_type="Nepal finance web results",
            results=web_results,
            fields=("title", "body", "href"),
        ),
        _format_search_results(
            query=nepal_query,
            result_type="Nepal finance news",
            results=news_results,
            fields=("date", "title", "body", "url", "source"),
        ),
    ]
    return "\n\n".join(sections)


def _alpha_vantage_query(params: dict[str, str]) -> dict[str, Any] | str:
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
    if not api_key:
        return (
            "Alpha Vantage API key is not configured. Set "
            "ALPHA_VANTAGE_API_KEY in .env to enable structured market data. "
            f"Docs: {ALPHA_VANTAGE_DOCS_URL}"
        )

    query_params = {**params, "apikey": api_key}
    url = f"{ALPHA_VANTAGE_URL}?{urlencode(query_params)}"
    request = Request(url, headers={"User-Agent": "multi-agent-finance-agent"})

    try:
        with urlopen(request, timeout=20) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return f"Alpha Vantage request failed with HTTP {exc.code}: {exc.reason}"
    except URLError as exc:
        return f"Alpha Vantage request failed: {exc.reason}"
    except TimeoutError:
        return "Alpha Vantage request timed out."

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return f"Alpha Vantage returned a non-JSON response: {_truncate(payload)}"

    provider_message = data.get("Note") or data.get("Information") or data.get("Error Message")
    if provider_message:
        return (
            "Alpha Vantage provider message: "
            f"{provider_message}\nSource: {ALPHA_VANTAGE_DOCS_URL}"
        )

    return data


def _format_fields(
    title: str,
    identifier: str,
    fields: dict[str, Any],
    source: str,
) -> str:
    lines = [title, f"Identifier: {identifier}"]
    for label, value in fields.items():
        if value in (None, "", "None", "-", {}):
            continue
        lines.append(f"{label}: {_truncate(str(value))}")
    lines.append(f"Source: {source}")
    return "\n".join(lines)


def _format_provider_empty(
    result_type: str,
    identifier: str,
    data: dict[str, Any],
) -> str:
    preview = _truncate(json.dumps(data, ensure_ascii=True))
    return (
        f"{result_type}\n"
        f"Identifier: {identifier}\n\n"
        "No structured result was returned by Alpha Vantage. "
        "Check the symbol/currency code or use finance news/search fallback.\n"
        f"Provider response: {preview}\n"
        f"Source: {ALPHA_VANTAGE_DOCS_URL}"
    )


def _format_search_results(
    query: str,
    result_type: str,
    results: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> str:
    if not results:
        return f"{result_type}\nQuery: {query}\n\nNo results found."

    context = f"{result_type}\nQuery: {query}\n"
    for idx, result in enumerate(results, start=1):
        context += f"\n{idx}. "
        lines = []
        for field in fields:
            value = result.get(field)
            if value in (None, "", {}, []):
                continue
            label = field.replace("_", " ").title()
            lines.append(f"{label}: {_truncate(str(value))}")
        context += "\n".join(lines)

    return context


def _format_search_error(query: str, result_type: str, error: Exception) -> str:
    return (
        f"{result_type}\n"
        f"Query: {query}\n\n"
        "No results found or the search provider failed.\n"
        f"Error: {error}"
    )


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _average(values: list[float | None]) -> float | None:
    clean_values = [value for value in values if value is not None]
    if not clean_values:
        return None
    return sum(clean_values) / len(clean_values)


def _format_number(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:,.2f}"


def _format_percent(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:+.2f}%"


def _truncate(text: str, max_length: int = MAX_FIELD_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."
