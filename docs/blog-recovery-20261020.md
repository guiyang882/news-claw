# October 20 metadata overflow recovery

The 07:32 writer (`480be71c4b9576d99e6c37e3070fb7d8`) failed at 07:44 after factual correction. Its Chinese homepage note contained 301 raw Markdown characters (limit 220); English summary 647 (limit 600), English homepage note 368 (limit 220). Long inline source URLs accounted for much of the overflow. The body was not over length. Hourly watchdogs reported `failure_outside_content_recovery`, so no automatic repair was attempted.

The website and writer now accept summaries up to 1,200 and homepage notes up to 600 raw characters in both languages. Titles remain capped at 220. The writer's shared length guidance repeats the limits during drafting, correction, humanizing and watchdog repair, explicitly counting Markdown URLs. Card excerpts remain controlled by the existing frontend presentation logic.

The exact metadata-overflow error is now recoverable. Unrelated schema, source safety, authentication and provider-denial failures remain outside this recovery path. Recovery still uses saved primary evidence and the approved outline, retains call history, and requires new factual and final reviews. The existing 16-call daily budget, two-recovery ceiling and provider circuits are unchanged.

Validation: nine website runtime/publication tests and 37 writer/watchdog/publication-surface tests passed. Added coverage for both language boundary values, rejection above each cap, identical website/writer limits, metadata recovery eligibility, and mandatory fresh reviews after recovery.

Deployed using rsync. The website Gunicorn workers were gracefully reloaded with HUP; systemd has no ExecReload configured. No frontend rebuild or unrelated service restart was needed.

Website change: `stocks-quant` commit `1305cde`, pushed to origin/main. Deployment preserved repository ownership; transfers must use `--no-owner --no-group` when rsync runs as root across macOS/Linux.

First bounded recovery `8555e20f9e47beae0b2f99f3b76139bf` passed initial factual review but failed final humanizer comparison: two source-supported details were added beyond the approved baseline. It was not published. After the configured cooldown, a second watchdog recovery `934c110b361e07d66ca316c960a18a47` was queued with nine calls already counted toward the unchanged 16-call daily limit.

The second recovery published successfully at 2026-10-20 14:46:09 Asia/Shanghai. Initial and final reviews both approved with no issues, within 13 cumulative model calls. Chinese 5,955 reading units (~20 minutes), English 3,523 words (~18 minutes).

Published slug: `control-should-organizations-retain-when-agents-handle-internal-2026-10-20`.
The delivery audit passed 15 local surface checks, including bilingual paginated listings and article pages. The public HTTPS article returned HTTP 200. The blog list shows the October 20 article first, nine cards per page and no horizontal overflow. Website source and news-claw source limits are both deployed; no task configuration or model budget was increased.
