# Problem Radar V1

A **working local-first research workspace** for finding publicly discussed problems and systematically validating whether they are opportunities. No paid AI API and no npm or pip installation required.

## Quick start

Python 3.10+ is required.

```bash
cd problem-radar-v1
python3 app.py
```

Open **http://localhost:8765**.

1. Click **Scan live sources**. Internet access is necessary for live collection.
2. Open a problem cluster, inspect the source evidence and read the original discussion.
3. Open **Market research**, add verified paid competitors and free alternatives, and save research notes.
4. Don't choose *Customer validation* until independent evidence justifies a real customer interview.

## How it works

- Hacker News: official Algolia HN search endpoints (stories and comments).
- GitHub: public REST issues search. Unauthenticated calls have a limited request quota; set a personal access token with `GITHUB_TOKEN` to increase the quota if needed.
- SQLite DB: `radar.db` (automatically created on first run; never bundled with sample discussions).
- Five starting clusters: Stripe reconciliation, client onboarding, invoice follow-up, client-document collection, SaaS renewals.
- Keyword-based pain detection; scores are **heuristics, not AI intelligence or proof of demand**.
- Competitor prices are recorded with links and dates; they are not continuously verified. The initial Synder reference should be independently rechecked against the vendor website before making decisions.
- Every recorded complaint needs a separate original source. A vendor feature page is **not** evidence of an unhappy customer.
- No scraping or automatic commercial social-platform access.
- No automatic recommendations to build.

## Optional token

```bash
GITHUB_TOKEN=github_pat_your_token python3 app.py
```

Keep tokens in your environment, not source files. The server binds to `127.0.0.1` for local-only access.

## Command-line tests

```bash
python3 -m unittest discover -s tests -v
```

## V1 limits / responsible use

This is a research prototype, not a fully autonomous SaaS. It requires the user to press Scan and be online. API limits and terms apply; there is no background scheduler yet. We intentionally do not label any opportunity 'validated' based on keyword counts. Source authors can overlap and issue comments can be duplicates. The pricing source record is a human-readable reference, not a live pricing crawler. No AI API is used; LLM enrichment, automated competitor verification, confidence metrics, daily scheduling and notifications belong to V2.

## Architecture

`app.py` implements a localhost HTTP server, public API connectors, persistence, a conservative research gate and JSON routes. `static/` contains the dashboard. Data are held in `radar.db`; back that file up to preserve research history.
