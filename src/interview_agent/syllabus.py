"""The mid-level AI engineer syllabus, one topic per day.

Ordered roughly by how often it comes up in real interviews for this level, so
the early days cover the ground most likely to be asked. Rotation is handled by
coach.py - this file is only the map.

Roughly two months of daily topics. When the list is exhausted it cycles back to
whatever was covered longest ago, which is close to spaced repetition.
"""

# (area, topic) - the topic is specific enough to generate one focused question
# rather than a survey answer.
SYLLABUS: list[tuple[str, str]] = [
    # --- RAG: the thing you will be asked about most -----------------------
    ("RAG", "Chunking strategy: fixed size vs semantic vs recursive, and how chunk size interacts with retrieval quality"),
    ("RAG", "Why hybrid retrieval beats pure vector search, and when BM25 alone wins"),
    ("RAG", "Reranking: cross-encoders vs bi-encoders, and where the latency budget goes"),
    ("RAG", "Query rewriting and HyDE: fixing the question rather than the index"),
    ("RAG", "Measuring RAG quality: recall@k, faithfulness, and answer relevance as separate failures"),
    ("RAG", "Diagnosing a hallucination: retrieval failure vs generation failure, and how to tell them apart"),
    ("RAG", "Handling documents that do not fit the context window, and lost-in-the-middle"),

    # --- Vector search ------------------------------------------------------
    ("Vector search", "HNSW: how the graph works, and what ef_construction and M actually trade"),
    ("Vector search", "IVF vs HNSW vs flat: recall, latency and memory at different corpus sizes"),
    ("Vector search", "Metadata filtering with ANN, and why pre- vs post-filtering changes recall"),
    ("Vector search", "Choosing an embedding model, and why dimensionality is not quality"),

    # --- LLM internals ------------------------------------------------------
    ("LLM internals", "Self-attention: the computation, and why cost is quadratic in sequence length"),
    ("LLM internals", "Multi-head attention: what different heads learn and why more is not always better"),
    ("LLM internals", "Tokenization: BPE, why token count is not word count, and how it breaks on code and non-English"),
    ("LLM internals", "Positional encoding: absolute vs rotary, and how RoPE enables context extension"),
    ("LLM internals", "The KV cache: what it stores, why it dominates memory, and what that means for batch size"),
    ("LLM internals", "Sampling: temperature, top-k, top-p, and when greedy decoding is correct"),
    ("LLM internals", "Encoder-only vs decoder-only vs encoder-decoder, and what each is actually for"),

    # --- Fine-tuning --------------------------------------------------------
    ("Fine-tuning", "LoRA: what the low-rank decomposition does, and how to choose rank and alpha"),
    ("Fine-tuning", "QLoRA and 4-bit quantization: what is lost and when it does not matter"),
    ("Fine-tuning", "Full fine-tuning vs LoRA vs prompting: choosing by data volume and budget"),
    ("Fine-tuning", "Catastrophic forgetting: why it happens and how to detect it before shipping"),
    ("Fine-tuning", "RLHF vs DPO: what preference data buys you, and why DPO is simpler"),
    ("Fine-tuning", "Building a fine-tuning dataset: size, quality, and contamination"),

    # --- Serving and cost ---------------------------------------------------
    ("Serving", "Continuous batching: why it beats static batching for LLM serving"),
    ("Serving", "Latency vs throughput: TTFT, inter-token latency, and which one users feel"),
    ("Serving", "Quantization at inference: INT8, INT4, and the accuracy/latency trade"),
    ("Serving", "Speculative decoding: how a draft model wins time"),
    ("Serving", "Cutting LLM cost in production: caching, routing, model tiering, prompt size"),
    ("Serving", "Rate limits and quotas: per-minute vs per-day, backoff, and cross-provider fallback"),

    # --- Agents -------------------------------------------------------------
    ("Agents", "Tool calling: how the model is constrained to a schema, and why it still fails"),
    ("Agents", "ReAct vs plan-and-execute: the trade between adaptability and token cost"),
    ("Agents", "Agent memory: short-term context, long-term stores, and what to compact away"),
    ("Agents", "Multi-agent systems: when parallel agents help and when they just multiply cost"),
    ("Agents", "Making an agent loop terminate: step limits, budgets, and detecting no progress"),

    # --- Evaluation ---------------------------------------------------------
    ("Evaluation", "Building a golden dataset: size, coverage, and keeping it honest"),
    ("Evaluation", "LLM-as-judge: where it correlates with humans and where it does not"),
    ("Evaluation", "Offline eval vs online metrics, and why they disagree"),
    ("Evaluation", "Regression testing a non-deterministic system"),

    # --- MLOps --------------------------------------------------------------
    ("MLOps", "Tracing an LLM application: what to capture and what it costs to store"),
    ("MLOps", "Detecting drift when there is no ground truth label"),
    ("MLOps", "Versioning prompts, models and data together so a result is reproducible"),
    ("MLOps", "Deploying a model safely: shadow, canary, and rollback"),

    # --- Classic ML still gets asked ---------------------------------------
    ("Classic ML", "Bias-variance: diagnosing underfitting vs overfitting from curves"),
    ("Classic ML", "Precision, recall, F1 and AUC: choosing the metric the problem needs"),
    ("Classic ML", "Class imbalance: resampling, class weights, and threshold tuning"),
    ("Classic ML", "Data leakage: the ways it sneaks in and how it is caught"),
    ("Classic ML", "Regularization: L1 vs L2, dropout, and early stopping"),
    ("Classic ML", "Cross-validation done right on time series and grouped data"),

    # --- System design ------------------------------------------------------
    ("System design", "Design a RAG system for 10 million documents with a 2-second latency budget"),
    ("System design", "Design an LLM gateway: routing, fallback, caching, quotas, observability"),
    ("System design", "Design a document-processing pipeline that must not lose a document"),
    ("System design", "Design evaluation and monitoring for a chatbot already in production"),
    ("System design", "Multi-tenant LLM serving: isolation, fair quotas, and cost attribution"),
]


def areas() -> list[str]:
    seen: list[str] = []
    for area, _ in SYLLABUS:
        if area not in seen:
            seen.append(area)
    return seen


def topic_id(area: str, topic: str) -> str:
    """Stable id used to record what has been covered."""
    return f"{area}::{topic[:60]}"
