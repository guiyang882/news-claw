# Market-pulse homepage · 2026-11-03

GrowthYoung opens with company developments, eight-company coverage and a source desk. The homepage and primary navigation no longer promote articles. Published article URLs, feeds and the article library remain accessible as an archive.

## Scheduled work

- Retain the existing Rocket Lab / SpaceX / Tesla collection and analysis, the five independent company collectors and briefs, operating reviews and dependency reviews. Request limits, model budgets and denial circuits are unchanged.
- Pause `daily-blog-primary-evidence`, `daily-blog-readiness`, `daily-blog-agy-codex`, `daily-blog-watchdog` and `daily-blog-delivery-audit`. Earlier compose/publish jobs remain disabled. Resume only on an explicit user request; watchdogs must not revive the article pipeline.
- Active website-producing tasks check `/` for `data-market-pulse="v1"`, using the existing local content / Next.js / HTTPS checks. Article-specific health checks remain with the disabled article tasks.
- `market-pulse-coverage-audit` runs hourly at :45 Asia/Shanghai. It reads the website's validated NewsStore and scheduler history, then checks the three local website layers. It performs no external source fetches, model calls, service restarts or automatic repairs.

## Coverage rules

All eight companies remain visible. Source recency uses original publication dates, never collection dates. Recent means the preceding seven days; future records are excluded. Exact company/source-URL duplicates count once. A filing directory establishes the filing only and is labeled as metadata, not operating results.

Homepage highlights require a supported bilingual brief and recent, same-company cited evidence; filing metadata alone is insufficient. They link to the full brief and evidence. Newer sources may not yet be covered. Historical baseline data is not relabeled as a current development.

The audit distinguishes no new disclosure from failure. No source in seven days is a coverage note, not a failure if collection is running. Missing/invalid briefs, missing sources, no successful collection in 24 hours, or a brief more than 48 hours behind newer recent sources produce a failed/needs-attention result with company-specific reasons. The scheduler retains the JSON report. This does not authorize extra model retries, bypassing provider restrictions, filling data gaps or restarting paused strategies.

## Deployment

Build and smoke-test a separate frontend candidate, then switch artifacts atomically with rollback. After deployment, synchronize only changed task IDs into SQLite using the same fields as `scripts/init_db.py`. Preserve history, budgets, circuits and unrelated task states; do not use broad init to override live pauses. Enqueue the coverage audit once and inspect its result. Runtime content updates require no frontend build.
