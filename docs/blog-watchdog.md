# Research blog edition watchdog

`daily-blog-watchdog` runs only on **Friday and Sunday at 20:15, 21:15 and 22:15, Asia/Shanghai**. It complements the 19:30 writer, 21:30 conditional second start and 22:55/23:55 delivery audits. Since 2026-10-27, other weekdays return `not_publication_day` before inspecting, enqueuing or calling any model. See [the publication calendar](blog-weekly-schedule.md). The scheduler reads its own task row; enabling this task requires no service restart.

## Scope and decisions

1. Validate today's bilingual runtime article hashes and actual API, home, library and article surfaces. A valid published article needs no model call. A published article with a surface failure is reported for attention, never regenerated.
2. Inspect writer/evidence/watchdog runs. Wait for queued or active work without starting a duplicate. Report a running job beyond its execution timeout plus 120 seconds (or a queue older than two hours); never kill a process or restart services.
3. If no model attempt exists, enqueue a missing writer once after readiness passes. If the official-body collector has not run at all, enqueue it once with its unchanged collection policy. Failed/denied collectors are not retried by the watchdog.
4. For a terminal editorial/length failure with a complete saved draft, Codex receives the saved selected-source packet, outline, rejection issues and draft. It returns structured bilingual draft JSON. Fresh independent factual review, humanizer and final review are mandatory before the existing publisher can write the runtime manifest.
5. An insufficient-evidence attempt can be replanned only after readiness passes and the actual source/evidence content changes. Changes to media metadata alone do not qualify. This recovery uses Codex for planning and drafting as well.
6. After recovery, recheck the real publication surfaces. Missing evidence, authentication/denial circuits, unsupported infrastructure failures, exhausted limits and review rejection remain explicit `needs_attention` results in news-claw, not false publication successes.

## Boundaries and limits

- Codex uses a **read-only sandbox**, no approval escalation, no shell tools, no web search and no subagents. It can produce content JSON, not operate the server. The existing Python validators/publisher perform the authorized runtime-content write.
- No arbitrary repair commands; no code/configuration/credential edits, service restarts, provider-circuit resets, site rebuilds, synthetic evidence or changes to other tasks.
- At most **two recovery attempts per Beijing day**, separated by **ten minutes**. Scheduled checks run hourly only within the edition evening; an operator can enqueue a second check after the cooldown. Active-work and provider-denial guards still apply. Attempts are reserved durably before model work; enqueue requests are reserved before execution so uncertain results cannot cause a duplicate start.
- At most **16 cumulative model calls** across the original writer, all recovery ancestors and all same-day watchdog attempts, including failed calls. Reused checkpoints are counted once. The regular writer's ten-call configuration remains unchanged. A repair needs room for four fresh calls; replanning needs five.
- The watchdog and writer share the existing `model-cli` lock. A separate watchdog lock protects its state. The existing publisher's daily lock and one-article-per-day check remain in force.
- The recovery config exists only in memory. It does not add persistent `manual_recovery` fields to the writer's task row or alter its schedule/enabled state. Existing failed-run evidence is retained.
- Recovery results preserve the original workflow business status/error so subsequent runs can continue from the saved checkpoint rather than lose the failure cause inside a wrapper.
- A humanizer length failure can receive one in-run repair using the same selected evidence and skill, followed by a fresh factual review and the normal final review. These extra calls share the existing daily cap; an unsupported, still-short or rejected repair cannot publish. Manual humanizer edits are not silently rewritten.

## Operations

Read-only preview (no model calls, enqueue, or state writes):

```sh
/mnt/quant/strategies/stocks-quant/web/.venv/bin/python -m workflows.blog_watchdog --check
```

Run through the normal scheduler:

```sh
bin/news-claw enqueue -task daily-blog-watchdog
```

Per-run decisions are in `data/runs/<run_id>/result.json`. Repairs also retain the source packet, outline, model-stage JSON, `recovery-audit.json`, `watchdog-recovery-result.json` and publication proof. Daily reservation state is `data/runs/blog-watchdog-days/YYYY-MM-DD.json`. Do not delete state or reset model counters to force retries.

Registration must target only this task row. Do not run the global configuration initializer to enable it: that could change unrelated paused tasks. To stop this supervisor, disable only `daily-blog-watchdog`; the existing writer and collector continue their original schedules.

## Verification

The watchdog unit tests cover healthy publication, surface mismatch, active/stalled work, missed starts, uncertain enqueue outcomes, source/provider denial, changed-evidence gating, cooldown, total-call accounting and scope limits. Integration tests use synthetic evidence, fake independent model verdicts and a temporary website/database; they exercise the actual draft validators and publisher, verify exactly one bilingual publication, and confirm a rejected review cannot publish. No production article or real model call is needed for those tests.

On 2026-10-16, 23 targeted tests passed on the Singapore host, including existing writer budget/provider regressions. Only the new task was registered; the other 32 task definitions were compared before/after and remained identical. Initial scheduled-engine run `6b68c4a34ffab686317cc2045718f9e4` returned `publication_verified`, with 11 local HTTP checks, zero external requests and zero model calls. No service restart or website rebuild was performed.
