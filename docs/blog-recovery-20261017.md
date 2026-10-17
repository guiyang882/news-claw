# 2026-10-17: recover invalid fact-check locators

The 07:30 writer started at 07:36 Asia/Shanghai and stopped at 07:48. Its correction stage appended source chapter names to four otherwise correct evidence-file paths, for example `data/normalized/documents/<hash>.json — A New Beginning for Windows PCs; Availability`. `build_draft` correctly rejected these as nonexistent exact locators.

The progress watchdog detected the failure but classified it as outside content recovery. This was a missing error category in both the watchdog's policy and the writer's checkpoint-recovery allowlist, not a collector failure or missing source body.

Changes:

- Allow bounded recovery of the exact `Fact check locator does not exist in the evidence packet` error. Unknown infrastructure errors remain ineligible.
- Constrain the draft JSON schema's `locator` field to the exact locators of the selected topic's evidence. Both ordinary writing and watchdog repair use this constraint. The existing validator still checks that each locator belongs to its stated source, and independent review still checks whether that evidence supports the claim.
- Remind correction and watchdog prompts to copy exact source/locator pairs, without appended headings or fragments.
- Add regression tests for classification, schema rejection of annotations/out-of-scope paths, and the complete recovery of a draft with a malformed locator through fresh factual and final review into a temporary bilingual publication.

The original failed run is `7d0fbc471cb60f127dd767d17636d0bd`. The watchdog recovery is `93b617cb72444a8c0b60630eeeb7b2bc`; it reuses the saved outline/evidence and preserves all five prior model calls. No server configuration, service restart, task schedule or daily recovery/call limit was changed. Source evidence and rejected drafts remain intact for audit.

Validation: 22 targeted watchdog and integration tests passed in the isolated staging directory. Real recovery execution uses the existing news-claw scheduler, read-only Codex configuration and validated runtime publisher.

## Follow-up: post-humanizer length and publication

The first recovery passed factual review but its humanizer reduced the English article to 2,976 reading units, below the unchanged 3,201-unit floor. Added one bounded in-run humanizer length repair using only the selected evidence and the same humanizer skill, followed by fresh factual and final reviews. Still-short, metadata-changing or rejected repairs cannot publish, and all calls remain subject to the existing budget. Manual humanizer edits are excluded from automatic rewriting.

The watchdog cooldown is now ten minutes instead of one hour. Its hourly schedule, maximum two recoveries/day and cumulative 16-call limit are unchanged. Only the watchdog's config_json was updated in the task database; every other task configuration was compared before/after and remained identical.

Second recovery `003144660c09f28a9a6b04880c80ddfe` published at **2026-10-17 10:36 Asia/Shanghai**, after new factual, humanizer and final-review stages. The English article passed at 3,252 units and the Chinese article at 5,524 units, so the new in-run length repair was not needed on this successful attempt. Twelve actual model calls were consumed across the original writer and both recoveries, including failures; no counters were reset.

Published path: `/blog/should-creators-buy-new-pc-local-ai-examining-2026-10-17`. Draft SHA-256: `b8297f7e1b515ff12be63f4cfbfe57a770bb3d13866d8739c8d8a3e680f3aaef`. The watchdog verified bilingual content and 11 local HTTP surfaces (article pages, API, home and library) with no issues. Runtime publishing updates the website without rebuilding or restarting services.

Verification for the follow-up: 24 watchdog/integration tests and five targeted writer regressions passed. Tests exercise the real validators/publisher in temporary storage, including bounded short-draft repair, metadata preservation, rejection, selected-source scope, manual-edit provenance and inherited invocation budgets.
