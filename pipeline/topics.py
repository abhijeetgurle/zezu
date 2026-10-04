"""Topic vocabulary shared by the keyword tagger and the LLM schema."""

import re

# topic -> keywords that suggest it (matched case-insensitively on word boundaries)
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "system-design": ["system design", "architecture", "design pattern", "trade-off", "tradeoff"],
    "distributed-systems": ["distributed", "consensus", "raft", "paxos", "replication", "partition", "sharding", "crdt", "eventual consistency"],
    "databases": ["database", "postgres", "postgresql", "mysql", "sqlite", "redis", "cassandra", "dynamodb", "index", "query planner", "lsm", "b-tree", "clickhouse", "duckdb"],
    "scalability": ["scale", "scaling", "scalability", "throughput", "load balancing", "high availability"],
    "performance": ["performance", "latency", "optimization", "profiling", "benchmark", "cache", "caching"],
    "reliability": ["incident", "outage", "postmortem", "post-mortem", "sre", "resilience", "chaos", "failover"],
    "observability": ["observability", "tracing", "opentelemetry", "metrics", "logging", "monitoring"],
    "infrastructure": ["kubernetes", "k8s", "docker", "terraform", "serverless", "cloud", "aws", "gcp", "azure", "devops", "ci/cd"],
    "networking": ["network", "tcp", "http/3", "quic", "dns", "cdn", "grpc", "load balancer"],
    "security": ["security", "vulnerability", "auth", "oauth", "encryption", "zero trust", "cve"],
    "data-engineering": ["kafka", "stream processing", "pipeline", "etl", "spark", "flink", "data lake", "iceberg"],
    "ai-engineering": ["llm", "rag", "agent", "embedding", "vector", "inference", "fine-tuning", "machine learning", "gpu"],
    "programming-languages": ["rust", "golang", "go 1.", "python", "typescript", "java", "zig", "compiler", "garbage collector", "wasm", "webassembly"],
    "backend": ["api", "microservice", "monolith", "backend", "rest", "graphql", "queue", "event-driven"],
    "frontend": ["frontend", "react", "css", "browser", "javascript framework"],
    "testing": ["testing", "test suite", "fuzzing", "property-based"],
    "career": ["career", "engineering manager", "staff engineer", "interview", "promotion", "hiring"],
}

TOPICS: list[str] = list(TOPIC_KEYWORDS)

_PATTERNS = {
    topic: re.compile(r"\b(" + "|".join(re.escape(k) for k in kws) + r")\b", re.IGNORECASE)
    for topic, kws in TOPIC_KEYWORDS.items()
}


def keyword_topics(text: str, limit: int = 4) -> list[str]:
    """Return topics whose keywords appear in text, most hits first."""
    hits = []
    for topic, pattern in _PATTERNS.items():
        n = len(pattern.findall(text))
        if n:
            hits.append((n, topic))
    hits.sort(reverse=True)
    return [t for _, t in hits[:limit]]


def is_relevant(text: str) -> bool:
    """Cheap pre-filter: does the text mention any topic keyword at all?"""
    return any(p.search(text) for p in _PATTERNS.values())
