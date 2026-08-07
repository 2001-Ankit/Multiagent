import json
import re

from langchain.tools import tool


URL_PATTERN = re.compile(r"https?://[^\s\])>,]+")


def _clean_text(value: str) -> str:
    lines = []
    for raw_line in str(value).splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(set(cell) <= {"-", ":", " "} for cell in cells):
                continue
            line = " - " + " | ".join(cell for cell in cells if cell)
        lines.append(line)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _first_sentence(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return "Here is the requested information."

    sentence_match = re.search(r"(.+?[.!?])(?:\s|$)", compact)
    sentence = sentence_match.group(1) if sentence_match else compact
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 3].rstrip() + "..."


def _extract_sources(text: str) -> list[str]:
    sources = []
    for url in URL_PATTERN.findall(text):
        if url not in sources:
            sources.append(url)
    return sources[:8]


def _subject_from_question(question: str) -> str:
    compact = re.sub(r"\s+", " ", str(question)).strip()
    if not compact:
        return "Information Update"
    subject = compact[:70].rstrip()
    return f"Information Update: {subject}"


def _format_email(question: str, answer: str) -> dict[str, str]:
    cleaned_answer = _clean_text(answer)
    sources = _extract_sources(cleaned_answer)

    sections = [
        "Hello Master,",
        "",
        "Here is the information you requested.",
        "",
        "Request",
        str(question).strip(),
        "",
        "Summary",
        _first_sentence(cleaned_answer),
        "",
        "Details",
        cleaned_answer,
    ]

    if sources:
        sections.extend(["", "Sources"])
        sections.extend(f"- {source}" for source in sources)

    sections.extend(["", "Regards,", "MarkBot"])

    return {
        "subject": _subject_from_question(question),
        "body": "\n".join(sections).strip(),
    }


def _format_whatsapp(question: str, answer: str) -> dict[str, str]:
    cleaned_answer = _clean_text(answer)

    # Add a short bold title only when the body does not already lead with it,
    # so briefings (which include their own title) are not double-headed and short
    # answers are not repeated as a "summary".
    compact_question = re.sub(r"\s+", " ", str(question)).strip()
    first_line = cleaned_answer.splitlines()[0].strip().lower() if cleaned_answer else ""
    if compact_question and compact_question.lower()[:40] not in first_line:
        body = f"*{compact_question[:80]}*\n\n{cleaned_answer}"
    else:
        body = cleaned_answer

    return {
        "subject": _subject_from_question(question),
        "body": body.strip(),
    }


@tool
def format_delivery_message(question: str, answer: str, channel: str = "email") -> str:
    """Format an agent answer into a clean delivery payload for email or chat channels."""
    channel_name = channel.lower().strip()
    if channel_name == "email":
        payload = _format_email(question, answer)
    elif channel_name in {"whatsapp", "chat", "sms"}:
        payload = _format_whatsapp(question, answer)
    else:
        raise ValueError(f"Unsupported delivery channel: {channel}")

    payload["channel"] = channel_name
    return json.dumps(payload, ensure_ascii=True)
