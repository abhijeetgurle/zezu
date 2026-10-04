"""JSON-file storage: the repo is the database.

data/latest.json        - recent items the site loads (ranked)
data/archive/YYYY-MM.json - every item ever saved, by month fetched
data/seen.json          - url hash -> date first seen, for dedupe
"""

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LATEST_DAYS = 56
LATEST_MAX = 400
SEEN_TTL_DAYS = 120

_TRACKING_PREFIXES = ("utm_", "ref", "source", "fbclid", "gclid", "mc_")


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(_TRACKING_PREFIXES)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."), path, urlencode(query), ""))


def url_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def rank_score(item: dict, now: datetime) -> float:
    """quality x freshness x source weight, plus a small popularity bonus."""
    published = datetime.fromisoformat(item["published"])
    age_days = max(0.0, (now - published).total_seconds() / 86400)
    freshness = 0.5 ** (age_days / 14)  # halves every two weeks
    popularity = math.log10(1 + item.get("popularity", 0)) / 3  # 1000 points -> +1
    return round((item["quality"] / 10) * freshness * item.get("weight", 1.0) + 0.2 * popularity, 4)


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir
        self.now = datetime.now(timezone.utc)
        self.seen: dict[str, str] = _read(data_dir / "seen.json", {})
        self.latest: list[dict] = _read(data_dir / "latest.json", {}).get("items", [])
        self.new_items: list[dict] = []

    def is_seen(self, url: str) -> bool:
        return url_id(url) in self.seen

    def add(self, item: dict) -> None:
        item["id"] = url_id(item["url"])
        item["fetched"] = self.now.isoformat(timespec="seconds")
        self.seen[item["id"]] = self.now.date().isoformat()
        self.new_items.append(item)

    def mark_seen(self, url: str) -> None:
        """Record an item we decided to drop, so we don't re-process it."""
        self.seen[url_id(url)] = self.now.date().isoformat()

    def save(self) -> None:
        # Archive new items by fetch month
        if self.new_items:
            archive_path = self.dir / "archive" / f"{self.now:%Y-%m}.json"
            archive = _read(archive_path, [])
            archive.extend(self.new_items)
            _write(archive_path, archive)

        # Rebuild latest: recent items, re-ranked
        cutoff = self.now - timedelta(days=LATEST_DAYS)
        items = {i["id"]: i for i in self.latest + self.new_items}
        recent = [i for i in items.values() if datetime.fromisoformat(i["published"]) >= cutoff]
        for i in recent:
            i["rank"] = rank_score(i, self.now)
        recent.sort(key=lambda i: i["rank"], reverse=True)
        _write(self.dir / "latest.json", {
            "generated_at": self.now.isoformat(timespec="seconds"),
            "items": recent[:LATEST_MAX],
        })

        # Forget very old seen entries so the file doesn't grow forever
        seen_cutoff = (self.now - timedelta(days=SEEN_TTL_DAYS)).date().isoformat()
        _write(self.dir / "seen.json", {k: v for k, v in self.seen.items() if v >= seen_cutoff})
