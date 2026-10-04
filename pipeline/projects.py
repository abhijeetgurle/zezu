"""Weekly "projects to build": ideas grounded in this week's trending repos and articles."""

import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

import anthropic

from enrich import MODEL, claude_configured

log = logging.getLogger(__name__)

PROJECTS_SCHEMA = {
    "type": "object",
    "properties": {
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "pitch": {"type": "string"},
                    "stack": {"type": "array", "items": {"type": "string"}},
                    "you_will_learn": {"type": "array", "items": {"type": "string"}},
                    "milestones": {"type": "array", "items": {"type": "string"}},
                    "scope": {"type": "string", "enum": ["weekend", "1-2 weeks", "month"]},
                    "inspired_by": {"type": "string"},
                },
                "required": ["title", "pitch", "stack", "you_will_learn", "milestones", "scope", "inspired_by"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["projects"],
    "additionalProperties": False,
}

SYSTEM = """You suggest hands-on projects for a software engineer who wants to learn system design \
and current technology by building things. Each project should be buildable by one person, use \
technology that is genuinely new or rising this week, and teach a real engineering concept \
(e.g. consistency, caching, backpressure, indexing, observability), not just glue APIs together. \
Ground each idea in the trending repositories or articles provided; put the repo or article URL \
that inspired it in inspired_by."""


def generate(trending: list[dict], latest: list[dict], client: anthropic.Anthropic) -> list[dict]:
    top_topics = Counter(t for i in latest for t in i.get("topics", [])).most_common(8)
    top_articles = sorted(latest, key=lambda i: i.get("rank", 0), reverse=True)[:15]
    context = {
        "trending_repos": [{k: r[k] for k in ("name", "url", "description", "language", "stars")} for r in trending],
        "popular_topics_this_week": [t for t, _ in top_topics],
        "top_articles": [{"title": a["title"], "url": a["url"], "summary": a.get("summary", "")} for a in top_articles],
    }
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": "Suggest 5 projects based on this week's signals:\n\n" + json.dumps(context, indent=1),
        }],
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": PROJECTS_SCHEMA},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason != "end_turn":
        log.warning("projects: unexpected stop_reason %s", response.stop_reason)
        return []
    return json.loads(next(b.text for b in response.content if b.type == "text"))["projects"]


def update(path: Path, trending: list[dict], latest: list[dict], now: datetime) -> None:
    projects = []
    if claude_configured() and trending:
        try:
            projects = generate(trending, latest, anthropic.Anthropic())
        except (anthropic.APIError, anthropic.WorkloadIdentityError) as e:
            log.warning("projects generation failed: %s", e)
    path.write_text(json.dumps({
        "generated_at": now.isoformat(timespec="seconds"),
        "projects": projects,
        "trending": trending,
    }, indent=1, ensure_ascii=False) + "\n")
    log.info("projects: wrote %d ideas, %d trending repos", len(projects), len(trending))
