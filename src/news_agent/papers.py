"""Research papers, from the arXiv API rather than news coverage.

News search returns articles *about* papers, usually without the paper. The
arXiv API returns the paper itself: title, the real abstract, authors and a
permanent link. No key, no rate limit worth worrying about.

Two different questions get two different answers:
- "what should every AI engineer have read" is a curated list, not a query
- "what is new this week" is a live fetch
Pretending the second can answer the first is how you get a reading list of
whatever happened to be posted yesterday.
"""

import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from langchain.tools import tool

API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}

# The categories an AI engineer actually reads.
CATEGORIES = {
    "cs.CL": "Language & LLMs",
    "cs.LG": "Machine learning",
    "cs.AI": "AI",
    "cs.IR": "Retrieval",
}

# Curated, not fetched. These are the papers the field is built on - a live query
# can never surface them because they are not new.
FOUNDATIONAL = [
    ("Attention Is All You Need", "https://arxiv.org/abs/1706.03762",
     "The transformer. Every model you use descends from this architecture."),
    ("BERT: Pre-training of Deep Bidirectional Transformers", "https://arxiv.org/abs/1810.04805",
     "Why encoder models still win at classification and retrieval."),
    ("Language Models are Few-Shot Learners (GPT-3)", "https://arxiv.org/abs/2005.14165",
     "Where in-context learning came from - the basis of prompting."),
    ("Retrieval-Augmented Generation for Knowledge-Intensive NLP", "https://arxiv.org/abs/2005.11401",
     "The original RAG paper. Read it before designing another pipeline."),
    ("LoRA: Low-Rank Adaptation of Large Language Models", "https://arxiv.org/abs/2106.09685",
     "Why you can fine-tune a large model on one GPU."),
    ("Chain-of-Thought Prompting Elicits Reasoning", "https://arxiv.org/abs/2201.11903",
     "The result that reframed prompting as eliciting a process, not an answer."),
    ("Training language models to follow instructions (InstructGPT)", "https://arxiv.org/abs/2203.02155",
     "RLHF, and why instruction-tuned models behave differently from base ones."),
    ("Direct Preference Optimization", "https://arxiv.org/abs/2305.18290",
     "Preference tuning without a reward model - now the common default."),
    ("ReAct: Synergizing Reasoning and Acting", "https://arxiv.org/abs/2210.03629",
     "The loop nearly every agent framework implements."),
    ("Efficient Memory Management for LLM Serving (PagedAttention/vLLM)", "https://arxiv.org/abs/2309.06180",
     "Why the KV cache dominates serving cost, and what to do about it."),
    ("Lost in the Middle: How Language Models Use Long Contexts", "https://arxiv.org/abs/2307.03172",
     "Why stuffing the context window degrades answers - essential for RAG."),
    ("Self-Consistency Improves Chain of Thought Reasoning", "https://arxiv.org/abs/2203.11171",
     "Sampling several paths and voting, a cheap accuracy win."),
]


def _fetch(query: str, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": limit,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    request = urllib.request.Request(
        f"{API}?{params}", headers={"User-Agent": "multi-agent-papers/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            root = ET.fromstring(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, ET.ParseError):
        return []

    papers = []
    for entry in root.findall("atom:entry", NS):
        def text(tag: str) -> str:
            node = entry.find(f"atom:{tag}", NS)
            return " ".join((node.text or "").split()) if node is not None else ""

        authors = [
            " ".join((a.text or "").split())
            for a in entry.findall("atom:author/atom:name", NS)
        ]
        papers.append({
            "title": text("title"),
            "abstract": text("summary"),
            "url": text("id"),
            "published": text("published")[:10],
            "authors": authors[:3],
        })
    return papers


@tool
def fetch_papers(topic: str = "", days_back: int = 14, max_results: int = 5) -> str:
    """Recent arXiv papers with their real abstracts and links.

    Pass a topic to search ("retrieval augmented generation", "agent memory"),
    or leave it blank for the newest across LLM, ML, AI and retrieval categories.
    """
    limit = max(3, min(int(max_results), 10))
    if topic.strip():
        query = f'all:"{topic.strip()}"'
    else:
        query = " OR ".join(f"cat:{code}" for code in CATEGORIES)

    papers = _fetch(query, limit)
    if not papers:
        return "Section: Papers\n\nNo papers returned from arXiv."

    lines = ["Section: Papers"]
    for index, paper in enumerate(papers, start=1):
        who = ", ".join(paper["authors"]) or "unknown"
        lines.append(
            f"\n{index}. Title: {paper['title']}"
            f"\n   Body: {paper['abstract'][:600]}"
            f"\n   Source: {who} | {paper['published']}"
            f"\n   Url: {paper['url']}"
        )
    return "\n".join(lines)


@tool
def foundational_papers(count: int = 3) -> str:
    """The papers every AI engineer should have read, with why each matters.

    Curated rather than searched: these are the field's foundations and a live
    query will never surface them, because they are not new.
    """
    picked = FOUNDATIONAL[: max(1, min(int(count), len(FOUNDATIONAL)))]
    lines = ["Section: Worth reading"]
    for index, (title, url, why) in enumerate(picked, start=1):
        lines.append(
            f"\n{index}. Title: {title}\n   Body: {why}\n   Url: {url}"
        )
    return "\n".join(lines)
