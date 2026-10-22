# Eight-company radar audit — 2026-10-22

Scope: Rocket Lab, SpaceX, Tesla, Google, Amazon, Coinbase, NVIDIA and TSMC. Checked the live Chinese and English brief pages, operations panels, dependency graphs/tables, source snapshots and news-claw task histories. All eight companies have working panels; this is not a claim that every company's evidence is equally current or complete.

## Evidence freshness at inspection (Asia/Shanghai)

| Company | Brief generation | Coverage observation |
| --- | --- | --- |
| Rocket Lab | 2026-10-22 15:17 | Brief visible; later source changes are marked pending synchronization. |
| SpaceX | 2026-10-22 15:17 | Brief visible; later source changes are marked pending synchronization. |
| Tesla | 2026-10-22 15:17 | Brief visible; later source changes are marked pending synchronization. |
| Google | 2026-10-22 10:29 | Brief and both language variants present. |
| Amazon | 2026-10-22 14:30 | Brief and both language variants present. |
| NVIDIA | 2026-10-22 02:30 | Brief visible after the earlier reader validation fix (website 4490ed1); later source changes remain explicit. |
| Coinbase | 2026-10-21 18:28 | Scheduled job works. Coverage is limited to SEC metadata and cached media leads; do not present headlines as verified operating results. |
| TSMC | 2026-10-17 06:27 | Collector and brief task run, but the brief input has not changed. The task skips duplicate generation. Latest brief input is SEC submission metadata, not a newly read full filing. Operations separately contain Q3 figures reviewed on October 19. |

No source or review dates were artificially advanced. Existing source access restrictions and paused strategies were left intact.

## Dependency publication failure

The daily `company-dependencies-review` workflow obtained approved bilingual candidates on October 21 and 22 but failed during merge with `Too many relationships`. NVIDIA already had ten rows; the website validator imposed a cumulative twelve-row ceiling. A single company's growth blocked the whole publication.

The shared website validator now permits up to 64 relationships per company. The workflow merges into a copy, preserves newer disclosures, and handles the capacity boundary per company. At capacity it saves the complete reviewed candidate to `deferred-relationships.json`, reports `capacity_needs_review`, and still publishes eligible changes for other companies. Existing relationships can be updated at capacity. It never silently evicts prior rows. Review acceptance requires both exact packet hashes, `approved=true` and an empty issue list.

## Recovery and validation

The two failed run records remain unchanged:

- `e07ef546184f1ff715a32de8544a5177`: three approved relationships.
- `76f1843ee88e0436b1f1afc5e4ad2fcf`: four approved relationships.

The recovery utility rechecks the original failure reason, JSON schemas, review verdict, candidate and document hashes, normalized cache bodies, source URLs and verbatim quotes, under the publication lock. It verifies there is no competing queued/running dependency job. No model calls or network source requests are made. Backup and receipts are retained under `playground/all-company-audit-20261022/`; repeated execution is rejected once the publication receipt exists.

Twelve focused workflow/website tests passed, covering rejected review protection, exact source binding, growth beyond twelve rows, the 64-row boundary, deferred candidate persistence, peer-company publication, and newer-disclosure preservation. The recovery preview verified all seven approved additions: NVIDIA 10 → 17; other company counts unchanged (Amazon 4, Coinbase 3, Google 5, Rocket Lab 6, SpaceX 4, Tesla 3, TSMC 6).

Only the Python website workers need a graceful reload for the validator change. No frontend rebuild, scheduler restart, source circuit reset or strategy activation is required.
