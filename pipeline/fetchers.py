"""Fetchers for each source type. Every fetcher returns a list of raw item dicts:

    {url, title, source, source_type, published (ISO str), excerpt, popularity, weight, trusted}

A failing source is logged and skipped so one broken feed never breaks a run.
"""

import calendar
import logging
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests

log = logging.getLogger(__name__)

USER_AGENT = "reading-feed/0.1 (personal reading list; +https://github.com)"
session = requests.Session()
session.headers["User-Agent"] = USER_AGENT
TIMEOUT = 20


def _iso(ts: float | None) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
    return dt.isoformat(timespec="seconds")


def _strip_html(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def fetch_rss(feeds: list[dict], default_max: int) -> list[dict]:
    items = []
    for feed in feeds:
        try:
            resp = session.get(feed["url"], timeout=TIMEOUT)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as e:
            log.warning("rss %s failed: %s", feed["name"], e)
            continue
        for entry in parsed.entries[: feed.get("max_items", default_max)]:
            link = entry.get("link")
            if not link:
                continue
            ts = entry.get("published_parsed") or entry.get("updated_parsed")
            items.append({
                "url": link,
                "title": _strip_html(entry.get("title", "")),
                "source": feed["name"],
                "source_type": "rss",
                "published": _iso(calendar.timegm(ts) if ts else None),
                "excerpt": _strip_html(entry.get("summary", ""))[:1000],
                "popularity": 0,
                "weight": feed.get("weight", 1.0),
                "trusted": feed.get("trusted", False),
            })
        log.info("rss %s: %d items", feed["name"], len(parsed.entries))
    return items


def fetch_hackernews(cfg: dict) -> list[dict]:
    since = int(time.time()) - cfg.get("lookback_hours", 48) * 3600
    params = {
        "tags": "story",
        "numericFilters": f"points>={cfg.get('min_points', 100)},created_at_i>{since}",
        "hitsPerPage": 100,
    }
    try:
        resp = session.get("https://hn.algolia.com/api/v1/search_by_date", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        hits = resp.json()["hits"]
    except Exception as e:
        log.warning("hackernews failed: %s", e)
        return []
    items = []
    for h in hits:
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
        items.append({
            "url": url,
            "title": h.get("title", ""),
            "source": "Hacker News",
            "source_type": "hackernews",
            "published": _iso(h.get("created_at_i")),
            "excerpt": "",
            "popularity": h.get("points", 0),
            "discussion": f"https://news.ycombinator.com/item?id={h['objectID']}",
            "weight": 1.0,
            "trusted": False,
        })
    log.info("hackernews: %d items", len(items))
    return items


def fetch_reddit(cfg: dict) -> list[dict]:
    items = []
    for sub in cfg.get("subreddits", []):
        try:
            resp = session.get(f"https://www.reddit.com/r/{sub}/top.json", params={"t": "week", "limit": 25}, timeout=TIMEOUT)
            resp.raise_for_status()
            posts = resp.json()["data"]["children"]
        except Exception as e:
            log.warning("reddit r/%s failed: %s", sub, e)
            continue
        for p in posts:
            d = p["data"]
            if d.get("score", 0) < cfg.get("min_score", 50) or d.get("stickied"):
                continue
            permalink = "https://www.reddit.com" + d["permalink"]
            # Link posts point at the article; self posts are the discussion itself.
            url = permalink if d.get("is_self") else d.get("url", permalink)
            items.append({
                "url": url,
                "title": d.get("title", ""),
                "source": f"r/{sub}",
                "source_type": "reddit",
                "published": _iso(d.get("created_utc")),
                "excerpt": (d.get("selftext") or "")[:1000],
                "popularity": d.get("score", 0),
                "discussion": permalink,
                "weight": cfg.get("weight", 1.0),
                "trusted": False,
            })
        time.sleep(1)  # be polite
    log.info("reddit: %d items", len(items))
    return items


def fetch_github_trending(cfg: dict, token: str | None = None) -> list[dict]:
    """Recently created repos with the most stars (a stable stand-in for the Trending page)."""
    since = (datetime.now(timezone.utc) - timedelta(days=cfg.get("lookback_days", 7))).date().isoformat()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {
        "q": f"created:>{since} stars:>={cfg.get('min_stars', 200)}",
        "sort": "stars",
        "order": "desc",
        "per_page": cfg.get("limit", 25),
    }
    try:
        resp = session.get("https://api.github.com/search/repositories", params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        repos = resp.json()["items"]
    except Exception as e:
        log.warning("github trending failed: %s", e)
        return []
    return [{
        "name": r["full_name"],
        "url": r["html_url"],
        "description": r.get("description") or "",
        "language": r.get("language") or "",
        "stars": r.get("stargazers_count", 0),
        "topics": r.get("topics", [])[:6],
    } for r in repos]
