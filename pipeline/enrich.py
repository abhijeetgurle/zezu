"""Article enrichment: extract readable text, then summarize/tag with Claude.

If no Claude credentials are configured (or a call fails), falls back to keyword tagging,
so the pipeline always works at $0.
"""

import json
import logging
import os

import anthropic
import trafilatura

from topics import TOPICS, keyword_topics

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL") or "claude-opus-5-5"
# Cost control: only the first N characters of each article are sent to Claude.
LLM_MAX_CHARS = int(os.environ.get("LLM_MAX_CHARS") or "12000")



def claude_configured() -> bool:
    """True if the SDK can authenticate: an API key (local runs) or Workload
    Identity Federation env vars (GitHub Actions)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_FEDERATION_RULE_ID"))


KINDS = ["deep-dive", "case-study", "tutorial", "paper", "opinion", "news", "release", "other"]
LEVELS = ["beginner", "intermediate", "advanced"]

ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "summary": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string", "enum": TOPICS}},
        "kind": {"type": "string", "enum": KINDS},
        "level": {"type": "string", "enum": LEVELS},
        "quality": {"type": "integer"},
    },
    "required": ["relevant", "summary", "topics", "kind", "level", "quality"],
    "additionalProperties": False,
}

SYSTEM = """You curate a personal reading list for a software engineer who wants to get better at \
system design, software engineering, and building projects with current technology.

For the article you are given, return:
- relevant: true if it would help that engineer learn or stay current; false for marketing, \
product announcements with no technical depth, listicles, or off-topic content.
- summary: 2-3 plain sentences on what the reader will learn. No hype.
- topics: 1-4 topics from the allowed list.
- kind and level: the best fit.
- quality: 1-10, where 8+ means a substantive piece worth an evening of reading."""


def extract_text(url: str) -> str:
    try:
        html = trafilatura.fetch_url(url)
        return (trafilatura.extract(html, include_comments=False) or "") if html else ""
    except Exception as e:
        log.debug("extract %s failed: %s", url, e)
        return ""


def keyword_enrich(item: dict, text: str) -> dict:
    body = text or item.get("excerpt", "")
    summary = body[:280].rsplit(" ", 1)[0] + "…" if len(body) > 280 else body
    return {
        "summary": summary,
        "topics": keyword_topics(f"{item['title']} {body}") or ["other"],
        "kind": "other",
        "level": "intermediate",
        "quality": 5,
        "enriched_by": "keywords",
    }


class Enricher:
    def __init__(self) -> None:
        self.client = anthropic.Anthropic() if claude_configured() else None
        if not self.client:
            log.info("no Claude credentials (API key or WIF); using keyword tagging only")

    def enrich(self, item: dict) -> dict | None:
        """Return enrichment fields, or None if Claude judged the article irrelevant."""
        text = extract_text(item["url"])
        if not self.client:
            return keyword_enrich(item, text)

        body = text or item.get("excerpt", "")
        prompt = (
            f"Title: {item['title']}\nSource: {item['source']}\nURL: {item['url']}\n\n"
            f"<article>\n{body[:LLM_MAX_CHARS]}\n</article>"
        )
        try:
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=4000,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": ARTICLE_SCHEMA},
                },
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.WorkloadIdentityError as e:
            # Auth won't recover mid-run: log once, then keyword-tag the rest.
            log.error("Claude auth (WIF token exchange) failed, disabling Claude for this run: %s", e)
            self.client = None
            return keyword_enrich(item, text)
        except anthropic.RateLimitError:
            log.warning("rate limited on %s; using keyword tagging", item["url"])
            return keyword_enrich(item, text)
        except anthropic.APIStatusError as e:
            log.warning("Claude API error %s on %s: %s", e.status_code, item["url"], e.message)
            return keyword_enrich(item, text)
        except anthropic.APIConnectionError as e:
            log.warning("Claude connection error on %s: %s", item["url"], e)
            return keyword_enrich(item, text)

        if response.stop_reason != "end_turn":
            log.warning("unexpected stop_reason %s on %s", response.stop_reason, item["url"])
            return keyword_enrich(item, text)

        data = json.loads(next(b.text for b in response.content if b.type == "text"))
        if not data["relevant"]:
            return None
        return {
            "summary": data["summary"],
            "topics": data["topics"] or ["other"],
            "kind": data["kind"],
            "level": data["level"],
            "quality": max(1, min(10, data["quality"])),
            "enriched_by": "claude",
        }
