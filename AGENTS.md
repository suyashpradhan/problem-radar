# Problem Radar — Codex project brief

## Goal
Build a private, local-first research engine that identifies repeated, verifiable operational pain in public discussions and investigates whether a small SaaS business can solve an underserved problem. The priority is evidence quality, not quantity of generated ideas.

## Existing application
- Python 3.10+ standard-library HTTP server (`app.py`), frontend (`static/`), SQLite, and unit tests (`tests/`).
- Runs with `python3 app.py`, then open http://localhost:8765.
- Collectors: Hacker News Algolia search and public GitHub issues search. Internet access required; GitHub rate limits apply.
- Five initial topics including Stripe payout reconciliation.
- Manual market research entries and an evidence gate. No paid AI API needed for V1.

## Product principles
1. Never present a complaint as validated business demand.
2. Every observation must link to its original source and publication date; deduplicate and preserve provenance.
3. Before recommending a build, research at least three relevant existing paid products, verify current pricing from vendor pages, identify free alternatives, and cite independent customer complaints.
4. Mark unavailable or stale pricing as unverified. Do not invent metrics, quotations, sources or market sizes.
5. Distinguish vendor marketing, anecdote, independent complaints, and buyer interviews.
6. Do not depend on unauthorized scraping or bypass platform access rules. Keep connectors modular.
7. Prefer narrow, low-maintenance, revenue-generating problems suitable for an individual developer; reject weak evidence.
8. Maintain a minimal, functional UI focused on evidence and research decisions.

## First Codex tasks
- Inspect code and run `python3 -m unittest discover -s tests -v`.
- Improve error handling, source deduplication and honest collection-status reporting.
- Add a repeatable job runner/scheduler with explicit rate limits, spending controls and source health.
- Add a research report schema for paid competitors, price verification dates, free alternatives, complaint links, and go/no-go reasoning.
- Preserve the local-first run path and avoid large rewrites unless justified.

## Non-goals for V1
- No unverified automatic go/build verdicts.
- No assumptions that an active ChatGPT subscription includes production model API credits.
- No inaccessible LinkedIn/Reddit bulk scraping.
