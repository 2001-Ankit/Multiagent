"""Finance data tools backed by Yahoo Finance (yfinance) - no API key required.

Replaces the old Alpha Vantage backend. Structured market data (quotes,
fundamentals, history, forex, crypto, financials, analyst view) comes from Yahoo
Finance. Macro/political context and Nepal/NEPSE coverage still use web/news search.
"""

from typing import Any

import yfinance as yf
from src.search_core import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 500
SOURCE = "Yahoo Finance (yfinance)"


def _fast_info(ticker: yf.Ticker, name: str) -> Any:
    fast_info = ticker.fast_info
    try:
        value = getattr(fast_info, name)
        if value is not None:
            return value
    except Exception:
        pass
    try:
        return fast_info[name]
    except Exception:
        return None


def _safe_info(ticker: yf.Ticker) -> dict:
    try:
        info = ticker.info
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


@tool
def get_stock_quote(symbol: str) -> str:
    """Look up the latest available stock or ETF quote for a market symbol."""
    symbol = symbol.strip().upper()
    try:
        ticker = yf.Ticker(symbol)
        price = _to_float(_fast_info(ticker, "last_price"))
        prev = _to_float(_fast_info(ticker, "previous_close"))
    except Exception as exc:
        return f"Stock quote lookup failed for {symbol}: {exc}"

    if price is None:
        return _empty("Stock quote", symbol)

    change = price - prev if (price is not None and prev) else None
    change_pct = (change / prev * 100) if (change is not None and prev) else None

    fields = {
        "Symbol": symbol,
        "Price": _format_number(price),
        "Change": _format_number(change),
        "Change Percent": _format_percent(change_pct),
        "Previous Close": _format_number(prev),
        "Open": _format_number(_to_float(_fast_info(ticker, "open"))),
        "Day High": _format_number(_to_float(_fast_info(ticker, "day_high"))),
        "Day Low": _format_number(_to_float(_fast_info(ticker, "day_low"))),
        "52W High": _format_number(_to_float(_fast_info(ticker, "year_high"))),
        "52W Low": _format_number(_to_float(_fast_info(ticker, "year_low"))),
        "Volume": _format_number(_to_float(_fast_info(ticker, "last_volume"))),
        "Market Cap": _format_number(_to_float(_fast_info(ticker, "market_cap"))),
        "Currency": _fast_info(ticker, "currency"),
    }
    return _format_fields("Stock quote", symbol, fields)


@tool
def get_company_overview(symbol: str) -> str:
    """Look up company overview and fundamental summary data for a symbol."""
    symbol = symbol.strip().upper()
    info = _safe_info(yf.Ticker(symbol))
    if not info:
        return _empty("Company overview", symbol)

    fields = {
        "Symbol": symbol,
        "Name": info.get("longName") or info.get("shortName"),
        "Exchange": info.get("exchange"),
        "Currency": info.get("currency"),
        "Country": info.get("country"),
        "Sector": info.get("sector"),
        "Industry": info.get("industry"),
        "Market Cap": _format_number(_to_float(info.get("marketCap"))),
        "Trailing PE": _format_number(_to_float(info.get("trailingPE"))),
        "Forward PE": _format_number(_to_float(info.get("forwardPE"))),
        "PEG Ratio": _format_number(_to_float(info.get("pegRatio"))),
        "Price/Book": _format_number(_to_float(info.get("priceToBook"))),
        "Dividend Yield": _format_percent(_pct(info.get("dividendYield"))),
        "Profit Margin": _format_percent(_pct(info.get("profitMargins"))),
        "Revenue Growth": _format_percent(_pct(info.get("revenueGrowth"))),
        "Earnings Growth": _format_percent(_pct(info.get("earningsGrowth"))),
        "Analyst Target": _format_number(_to_float(info.get("targetMeanPrice"))),
        "Recommendation": info.get("recommendationKey"),
        "52W High": _format_number(_to_float(info.get("fiftyTwoWeekHigh"))),
        "52W Low": _format_number(_to_float(info.get("fiftyTwoWeekLow"))),
    }
    summary = info.get("longBusinessSummary")
    if summary:
        fields["Business Summary"] = _truncate(str(summary))
    return _format_fields("Company overview", symbol, fields)


@tool
def get_stock_history(symbol: str, days: int = 30) -> str:
    """Look up recent daily stock history for trend, volume, and price-action analysis."""
    symbol = symbol.strip().upper()
    safe_days = max(5, min(int(days), 200))
    period = "6mo" if safe_days <= 120 else "1y"
    try:
        frame = yf.Ticker(symbol).history(period=period, interval="1d")
    except Exception as exc:
        return f"Stock history lookup failed for {symbol}: {exc}"

    if frame is None or frame.empty:
        return _empty("Stock history", symbol)

    frame = frame.tail(safe_days)
    closes = [float(x) for x in frame["Close"].tolist()]
    highs = [float(x) for x in frame["High"].tolist()]
    lows = [float(x) for x in frame["Low"].tolist()]
    volumes = [float(x) for x in frame["Volume"].tolist()]
    dates = [d.strftime("%Y-%m-%d") for d in frame.index]

    latest_close = closes[-1]
    oldest_close = closes[0]
    close_change = (
        ((latest_close - oldest_close) / oldest_close) * 100 if oldest_close else None
    )

    recent_volume = _average(volumes[-5:])
    prior_volume = _average(volumes[-20:-5])
    volume_signal = None
    if recent_volume and prior_volume:
        volume_signal = ((recent_volume - prior_volume) / prior_volume) * 100

    fields = {
        "Symbol": symbol,
        "Window Days": len(closes),
        "Latest Date": dates[-1],
        "Latest Close": _format_number(latest_close),
        "Window Change Percent": _format_percent(close_change),
        "Window High": _format_number(max(highs) if highs else None),
        "Window Low": _format_number(min(lows) if lows else None),
        "Average Recent Volume 5D": _format_number(recent_volume),
        "Average Prior Volume": _format_number(prior_volume),
        "Recent Volume Change Percent": _format_percent(volume_signal),
    }
    return _format_fields("Stock history and demand/supply snapshot", symbol, fields)


@tool
def get_forex_rate(from_currency: str, to_currency: str) -> str:
    """Look up the latest available exchange rate between two currencies."""
    from_currency = from_currency.strip().upper()
    to_currency = to_currency.strip().upper()
    pair = f"{from_currency}{to_currency}=X"
    try:
        ticker = yf.Ticker(pair)
        rate = _to_float(_fast_info(ticker, "last_price"))
    except Exception as exc:
        return f"Forex lookup failed for {from_currency}/{to_currency}: {exc}"

    if rate is None:
        return _empty("Forex rate", f"{from_currency}/{to_currency}")

    fields = {
        "From": from_currency,
        "To": to_currency,
        "Exchange Rate": _format_number(rate),
        "Previous Close": _format_number(_to_float(_fast_info(ticker, "previous_close"))),
        "Day High": _format_number(_to_float(_fast_info(ticker, "day_high"))),
        "Day Low": _format_number(_to_float(_fast_info(ticker, "day_low"))),
    }
    return _format_fields("Forex rate", f"{from_currency}/{to_currency}", fields)


@tool
def get_crypto_rate(symbol: str, market: str = "USD") -> str:
    """Look up the latest available cryptocurrency exchange rate."""
    symbol = symbol.strip().upper()
    market = market.strip().upper()
    pair = f"{symbol}-{market}"
    try:
        ticker = yf.Ticker(pair)
        rate = _to_float(_fast_info(ticker, "last_price"))
    except Exception as exc:
        return f"Crypto lookup failed for {symbol}/{market}: {exc}"

    if rate is None:
        return _empty("Crypto rate", f"{symbol}/{market}")

    prev = _to_float(_fast_info(ticker, "previous_close"))
    change_pct = ((rate - prev) / prev * 100) if prev else None
    fields = {
        "Symbol": f"{symbol}/{market}",
        "Price": _format_number(rate),
        "Previous Close": _format_number(prev),
        "Change Percent": _format_percent(change_pct),
        "Day High": _format_number(_to_float(_fast_info(ticker, "day_high"))),
        "Day Low": _format_number(_to_float(_fast_info(ticker, "day_low"))),
        "Market Cap": _format_number(_to_float(_fast_info(ticker, "market_cap"))),
    }
    return _format_fields("Crypto rate", f"{symbol}/{market}", fields)


@tool
def get_financials(symbol: str) -> str:
    """Look up recent income-statement highlights (revenue, income, margins) for a symbol."""
    symbol = symbol.strip().upper()
    try:
        stmt = yf.Ticker(symbol).income_stmt
    except Exception as exc:
        return f"Financials lookup failed for {symbol}: {exc}"

    if stmt is None or getattr(stmt, "empty", True):
        return _empty("Financials", symbol)

    wanted = ["Total Revenue", "Gross Profit", "Operating Income", "Net Income", "EBITDA"]
    lines = [f"Financials (annual)\nIdentifier: {symbol}"]
    periods = [str(col)[:10] for col in stmt.columns[:3]]
    lines.append("Periods: " + ", ".join(periods))
    for row in wanted:
        if row in stmt.index:
            values = []
            for col in stmt.columns[:3]:
                values.append(_format_number(_to_float(stmt.loc[row, col])))
            lines.append(f"{row}: " + " | ".join(v or "-" for v in values))
    lines.append(f"Source: {SOURCE}")
    return "\n".join(lines)


@tool
def get_analyst_view(symbol: str) -> str:
    """Look up analyst recommendation, price targets, and rating for a symbol."""
    symbol = symbol.strip().upper()
    info = _safe_info(yf.Ticker(symbol))
    if not info:
        return _empty("Analyst view", symbol)

    fields = {
        "Symbol": symbol,
        "Recommendation": info.get("recommendationKey"),
        "Number of Analysts": info.get("numberOfAnalystOpinions"),
        "Target Mean": _format_number(_to_float(info.get("targetMeanPrice"))),
        "Target High": _format_number(_to_float(info.get("targetHighPrice"))),
        "Target Low": _format_number(_to_float(info.get("targetLowPrice"))),
        "Current Price": _format_number(_to_float(info.get("currentPrice"))),
    }
    return _format_fields("Analyst view", symbol, fields)


COMMODITY_TICKERS = {
    "gold": "GC=F",
    "silver": "SI=F",
    "platinum": "PL=F",
    "palladium": "PA=F",
    "copper": "HG=F",
    "oil": "CL=F",
    "crude": "CL=F",
    "wti": "CL=F",
    "brent": "BZ=F",
    "natural gas": "NG=F",
    "natgas": "NG=F",
    "gas": "NG=F",
    "wheat": "ZW=F",
    "corn": "ZC=F",
    "soybean": "ZS=F",
    "soybeans": "ZS=F",
    "coffee": "KC=F",
    "sugar": "SB=F",
    "cotton": "CT=F",
}

# Global dashboard: the handful of prices that set the tone for everything else.
MARKET_SNAPSHOT = [
    ("S&P 500", "^GSPC"),
    ("Nasdaq", "^IXIC"),
    ("Dow Jones", "^DJI"),
    ("Gold", "GC=F"),
    ("WTI Crude Oil", "CL=F"),
    ("US Dollar Index", "DX-Y.NYB"),
    ("US 10Y Yield", "^TNX"),
    ("Volatility (VIX)", "^VIX"),
    ("Bitcoin", "BTC-USD"),
]


@tool
def get_commodity_price(name: str) -> str:
    """Look up the latest price for a commodity (e.g. gold, oil, copper, wheat, gas).

    Commodities drive costs and inflation, so they ripple from global macro down to
    niche markets. Accepts a common name or a Yahoo futures ticker (e.g. GC=F).
    """
    key = name.strip().lower()
    ticker_symbol = COMMODITY_TICKERS.get(key, name.strip().upper())
    try:
        ticker = yf.Ticker(ticker_symbol)
        price = _to_float(_fast_info(ticker, "last_price"))
        prev = _to_float(_fast_info(ticker, "previous_close"))
    except Exception as exc:
        return f"Commodity lookup failed for {name}: {exc}"

    if price is None:
        return _empty("Commodity price", f"{name} ({ticker_symbol})")

    change_pct = ((price - prev) / prev * 100) if prev else None
    fields = {
        "Commodity": name.strip().title(),
        "Ticker": ticker_symbol,
        "Price": _format_number(price),
        "Previous Close": _format_number(prev),
        "Change Percent": _format_percent(change_pct),
        "Day High": _format_number(_to_float(_fast_info(ticker, "day_high"))),
        "Day Low": _format_number(_to_float(_fast_info(ticker, "day_low"))),
    }
    return _format_fields("Commodity price", ticker_symbol, fields)


@tool
def get_market_snapshot() -> str:
    """Get a one-glance snapshot of global markets: indices, gold, oil, the dollar,
    10-year yield, volatility, and Bitcoin - with each one's daily change.

    Use this first for macro awareness: it shows the current world scenario (risk-on
    vs risk-off, rates, inflation pressure, dollar strength) that drives everything
    from global indices down to niche markets.
    """
    lines = ["Global market snapshot"]
    for label, ticker_symbol in MARKET_SNAPSHOT:
        try:
            ticker = yf.Ticker(ticker_symbol)
            price = _to_float(_fast_info(ticker, "last_price"))
            prev = _to_float(_fast_info(ticker, "previous_close"))
        except Exception:
            price = prev = None
        if price is None:
            lines.append(f"- {label}: unavailable")
            continue
        change_pct = ((price - prev) / prev * 100) if prev else None
        lines.append(
            f"- {label}: {_format_number(price)} ({_format_percent(change_pct) or 'n/a'})"
        )
    lines.append(f"Source: {SOURCE}")
    return "\n".join(lines)


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


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _format_fields(title: str, identifier: str, fields: dict[str, Any]) -> str:
    lines = [title, f"Identifier: {identifier}"]
    for label, value in fields.items():
        if value in (None, "", "None", "-", {}):
            continue
        lines.append(f"{label}: {_truncate(str(value))}")
    lines.append(f"Source: {SOURCE}")
    return "\n".join(lines)


def _empty(result_type: str, identifier: str) -> str:
    return (
        f"{result_type}\nIdentifier: {identifier}\n\n"
        "No data was returned. Check the symbol/pair (e.g. AAPL, BTC-USD, EURUSD) or "
        "use finance news/search as a fallback.\n"
        f"Source: {SOURCE}"
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
        result = float(value)
        if result != result:  # NaN check
            return None
        return result
    except (TypeError, ValueError):
        return None


def _pct(value: Any) -> float | None:
    """Yahoo returns ratios (0.23) for yields/margins; convert to percent (23.0)."""
    number = _to_float(value)
    return number * 100 if number is not None else None


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
