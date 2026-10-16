# 2026-10-16 daily blog recovery

The scheduled evidence collection succeeded and supplied eight complete primary-source bodies. The 07:30 writing task started, but publication stopped at 07:50 (Asia/Shanghai) after factual review rejected a translation of “in development” as “under construction.” The source did not establish physical construction. The initial correction had already addressed numerical/platform scope and inline citations, but missed this status distinction.

## Changes

- Draft, correction and humanizer prompts explicitly preserve project maturity and modal language in both languages, tables and summaries. They also distinguish the objects covered by a number or platform-availability claim.
- The public bibliography generator removes the collector's terminal ` — article body` label from publisher names. This was added after final review found that the generator reintroduced the label after humanizer editing; asking a model to edit its own prose could not fix that generated appendix. The source evidence packet remains unchanged.
- Three regression tests cover bilingual generated references, separator variants, preservation of original source metadata, unrelated prose/names and existing bibliographies.

## Recovery and review trail

- Scheduled failed run: `9d175d90cc85d118d4b9252f0a053972` (six model calls).
- Manual recovery: `caccf2d58dc0731b7e4da467c20aec91`. Reused the outline/draft; the narrowly corrected bilingual draft passed fresh factual review. Final review accepted facts, citations and translations but rejected the generated bibliography label. A model correction could not change the publisher-generated appendix. The run stopped at the cumulative ten-call cap.
- Final recovery: `4bfc9cb3787f4c0228f1787db8071ca1`. After fixing the generator, reused the approved factual-review checkpoint and unchanged humanizer response, then obtained a fresh final verdict bound to the reconstructed article hash. The verdict approved facts, citations, bilingual consistency and humanizer compliance with no issues.
- This operator recovery had a temporary cumulative cap of **11**, retaining all ten ancestor calls and allowing exactly one new final review. No calls, failed runs, provider circuits or day markers were erased. After publication the task DB's temporary recovery setting was removed and its normal cap restored to **10**; the tracked daily task config was not changed.
- Published at **2026-10-16 16:24 Asia/Shanghai**, slug `small-labs-actually-use-europe-expanding-ai-compute-2026-10-16`.
- Article SHA-256: `644b31d0a73828105ddee878fc04b740774859460aaa49560b6e1697e54f11bc`.

## Validation

Five existing recovery/review tests passed, including inherited-budget accounting, rejection handling, saved-checkpoint reuse and mandatory final humanizer approval. All three new reference-label tests passed. The delivery audit reported `publication_verified` with bilingual source validation and 11 successful local HTTP surface checks (API catalogue, both home/library pages, navigation and article pages). No new source crawling was required.

Publication uses the validated runtime manifest; no frontend rebuild or service restart is required. Failed-run artifacts and the exact publication approval proof remain on the server under `data/runs` and the website runtime's `automation-reviews` directory.
