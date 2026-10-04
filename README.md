# Weekly Reading

A personal reading list on system design and software engineering, plus weekly "projects to build" ideas.
It runs on GitHub Actions and GitHub Pages, with no database and no servers.

```
GitHub Actions (weekly, Monday 03:17 UTC)
  └─ pipeline/main.py
       1. fetch: RSS (eng blogs, newsletters, Lobsters, dev.to, arXiv), Hacker News, Reddit
       2. dedupe against data/seen.json, keyword pre-filter
       3. enrich: Claude summary/topics/quality (keyword tagging if no API key)
       4. write data/latest.json + data/archive/YYYY-MM.json
       5. projects: GitHub trending repos + Claude → data/projects.json
  └─ commit data/ → deploy site/ + data/ to GitHub Pages
```

## Setup

1. Create a **public** GitHub repo and push this folder to `main`. GitHub Pages is free for public repos; private repos need a paid plan.
2. **Settings → Pages → Source: GitHub Actions**.
3. (Optional) **Settings → Secrets and variables → Actions**:
   - Secret `ANTHROPIC_API_KEY`: turns on Claude summaries and project ideas. Without it, everything still works, using keyword tagging only.
   - Variable `CLAUDE_MODEL`: defaults to `claude-opus-5-5`. Set `claude-haiku-4-5` for roughly 4x lower cost.
   - Variable `MAX_LLM_PER_RUN`: defaults to `60` articles per week.
4. **Actions → fetch-and-deploy → Run workflow** for the first run. After that it runs every Monday.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r pipeline/requirements.txt
python pipeline/main.py --max-llm 10      # add ANTHROPIC_API_KEY=... to use Claude
python3 -m http.server 8000               # open http://localhost:8000/site/
```

## Customizing

- **Sources:** edit `pipeline/sources.yaml`. `weight` changes how much a source counts in ranking. `trusted: true` skips the keyword pre-filter.
- **Topics:** edit `pipeline/topics.py`. The same list is used by the keyword tagger and the Claude output schema.
- **Ranking:** see `rank_score` in `pipeline/store.py` (quality × freshness × source weight + popularity). The site also boosts topics you've liked.
- **Schedule:** the `cron` line in `.github/workflows/fetch.yml`.

## Cost

| | Cost |
|---|---|
| GitHub Actions, Pages, repo | $0 |
| Claude, 60 articles/week with `claude-opus-5-5` | ~$1–3/week (rough estimate) |
| Claude with `claude-haiku-4-5` | ~$0.25–0.75/week (rough estimate) |
| No API key | $0 |

Each article sends at most `LLM_MAX_CHARS` (default 12,000) characters to Claude.
Articles that don't pass the keyword filter never reach Claude.

## Known limitations

- **Reddit** returns `403 Blocked` for unauthenticated requests. It's logged and skipped. To enable it, register a free Reddit app and switch `fetch_reddit` to OAuth.
- **Medium-hosted blogs** (Netflix, Airbnb, Pinterest) block text extraction, so those articles are summarized from the RSS excerpt.
- **arXiv** feeds only list the latest day's papers, so a weekly run sees one day's worth.
- Likes, saves and read state are stored in your browser's localStorage. They don't sync across devices.
- Twitter/X and Bluesky aren't included yet.
