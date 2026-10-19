# October 18–19 daily blog recovery

The public catalogue and origin still ended at October 17 when checked on October 19.
Both daily schedules had run. English length failures and rejected fact-check scopes prevented publication;
the watchdog exhausted two daily recovery attempts. Failed model reviews and day markers were retained.

## Workflow corrections

- A fact-check has one evidence locator. Draft and recovery prompts now require splitting a multi-announcement claim into separately supported entries, and checking titles/abstracts for unsupported equivalence.
- Within the unchanged 16-call automatic daily budget, the watchdog reserves the ordinary repair, factual review, humanizer and final review first. Remaining capacity may fund one factual correction plus a new review and one draft-length repair. The runner continues to enforce its hard cap; there is no unbounded retry or review bypass.
- Preserve a complete `00-watchdog-repair` response when validation stops before it reaches the writer checkpoint.
- Explicitly manual writer recovery may consume a failed blog-watchdog checkpoint. Other tasks, nonterminal checkpoints, cron backfills and invalid day/evidence combinations remain rejected.
- A complete draft stopped by a cumulative invocation cap can resume through fresh factual, humanizer and final review. No counters are erased.
- Delivery verification follows local `rel=next` library links in each language instead of requiring the full catalogue on page one. External, malformed and repeated pagination targets are rejected before fetching.

## Operator recovery

Each manual queue snapshot retains all ancestor calls and permits at most eight additional calls for the requested correction/publication. Temporary config is restored immediately after the engine captures the queue snapshot. Normal scheduled limits remain 10 writer calls and 16 watchdog calls; the two automatic recoveries/day and provider-denial circuits remain unchanged. No new collection, trading task, service restart or frontend build is required for validated runtime articles.

October 18 uses its saved October 18 evidence and is explicitly marked as an archived article published on October 19. October 19's title is narrowed to the safety-stack verification question instead of asserting identical implementations.

## Validation

35 targeted offline tests passed, including rejected re-review, successful bounded correction, failed-watchdog ownership, pre-review budget checkpoint recovery and bilingual pagination. The full 118-test run had one existing source-cache fixture failure (`test_discovered_page_is_retained_beyond_feed_window_and_not_truncated`); the same failure was reproduced against unmodified production code. It was not hidden or waived by changing production collection policy.

## Published results

- October 18: `2cb77e6763b34f46deee2fc06a6b00c6`, published October 19 at 15:48:04 UTC+8. Title: 奔驰与沃尔沃计划采用相近驾驶技术，购车者能据此判断什么？ Initial factual review passed; final review required three nearby source links in each language; correction and re-review passed. All 11 ancestral model calls are retained; five new calls were used. The preceding operator queue `bcb115c4cfb7dbdb16e8fdd43f569b58` stopped before any new model invocation because an operator-supplied per-run limit was incorrectly lower than the inherited counter; its failed marker and artifacts remain in the recovery chain.
- October 19: `864ab5c3c20f1274bf9c0adae35b11aa`, published at 15:53:31 UTC+8. Title: 多一套驾驶安全栈，需要什么证据证明它增加了保护？ Five ancestral calls retained; three new calls for factual review, humanizer and final review. Both independent verdicts approved with no final issues.
- Runtime source hashes and both languages validated for both articles. Each date passed 15 loopback delivery checks including API catalogue, homepage, all three library pages, navigation and article pages. A normal `daily-blog-delivery-audit` was queued as `00c9cc3ec703516e191fd0ece0479d68` after publication.
- Mobile browser inspection confirmed no horizontal page overflow; the October 19 article rendered two Mermaid diagrams and three MathML elements. Archived October 18 content carries the explicit October 19 publication notice.

The publication files are runtime content consumed immediately by the existing Next.js/Python bridge. No website source code or service configuration was modified for this recovery.
