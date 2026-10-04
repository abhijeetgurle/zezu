"""Run one fetch -> filter -> enrich -> store cycle.

Usage:
    python pipeline/main.py                  # normal (weekly) run
    python pipeline/main.py --max-llm 5      # limit Claude calls (cost control)
"""

import argparse
import logging
import os
from collections import defaultdict
from itertools import zip_longest
from pathlib import Path

import yaml

import fetchers
import projects
from enrich import Enricher
from store import Store, canonical_url
from topics import is_relevant

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

log = logging.getLogger("pipeline")


def collect(cfg: dict) -> list[dict]:
    items = fetchers.fetch_rss(cfg.get("rss", []), cfg.get("max_items_per_feed", 20))
    if "hackernews" in cfg:
        items += fetchers.fetch_hackernews(cfg["hackernews"])
    if "reddit" in cfg:
        items += fetchers.fetch_reddit(cfg["reddit"])
    return items


def round_robin(items: list[dict]) -> list[dict]:
    """Interleave sources (most popular / newest first within each) so the LLM cap
    is spread across sources instead of being used up by whichever feed comes first."""
    by_source: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_source[item["source"]].append(item)
    for group in by_source.values():
        group.sort(key=lambda i: (i["popularity"], i["published"]), reverse=True)
    out = []
    for row in zip_longest(*by_source.values()):
        out.extend(i for i in row if i is not None)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-llm", type=int, default=int(os.environ.get("MAX_LLM_PER_RUN") or "60"),
                        help="max articles to enrich per run; the rest wait for the next run")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Sites that block text extraction are expected; we fall back to the feed excerpt.
    logging.getLogger("trafilatura").setLevel(logging.CRITICAL)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    cfg = yaml.safe_load((Path(__file__).parent / "sources.yaml").read_text())
    store = Store(DATA_DIR)

    # 1. Collect, dedupe against history and within this batch
    candidates: dict[str, dict] = {}
    for item in collect(cfg):
        if not item["title"] or store.is_seen(item["url"]):
            continue
        key = canonical_url(item["url"])
        prev = candidates.get(key)
        # Same article from several sources: keep the most popular copy
        if not prev or item["popularity"] > prev["popularity"]:
            candidates[key] = item
    log.info("%d new candidates", len(candidates))

    # 2. Cheap keyword pre-filter before spending any LLM calls
    queue = []
    for item in candidates.values():
        if item["trusted"] or is_relevant(f"{item['title']} {item['excerpt']}"):
            queue.append(item)
        else:
            store.mark_seen(item["url"])
    queue = round_robin(queue)
    log.info("%d passed pre-filter; enriching up to %d", len(queue), args.max_llm)

    # 3. Enrich (items over the cap stay unseen and are picked up next run)
    enricher = Enricher()
    kept = 0
    for item in queue[: args.max_llm]:
        fields = enricher.enrich(item)
        if fields is None:
            store.mark_seen(item["url"])
            continue
        item.update(fields)
        item.pop("trusted", None)
        item.pop("excerpt", None)
        store.add(item)
        kept += 1
    log.info("kept %d new articles", kept)

    store.save()

    # 4. This week's project ideas
    trending = fetchers.fetch_github_trending(cfg.get("github_trending", {}), os.environ.get("GITHUB_TOKEN"))
    projects.update(DATA_DIR / "projects.json", trending, store.latest + store.new_items, store.now)


if __name__ == "__main__":
    main()
