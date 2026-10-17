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
