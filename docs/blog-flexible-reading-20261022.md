# Evidence-based article length — 2026-10-22

The user approved evidence-supported 8–12 minute bilingual briefs when the available
material cannot support the existing approximately 20 minute research format.
This extends the reliability changes in `blog-reliability-20261022.md`.

## Policy and implementation

- The existing daily writer can select target 20 / tolerance 3 or target 10 /
  tolerance 2. The planner chooses once from explicitly configured formats,
  recording the target and per-language section budgets in the saved outline.
- Planning must consider the shorter supported format before returning insufficient
  evidence solely because a long article is unwarranted. It may still stop when
  neither format is supported. No padding, invented facts or relaxed source review.
- Both languages use the selected format throughout drafting, measured validation,
  corrections, humanizing and watchdog/manual recovery. Existing saved 20 minute
  outlines retain their original target. Configurations without `formats` retain
  the original single-format behavior.
- Reading labels are calculated from the actual text, not the model's label.
  The existing rounding rule is unchanged: ceil(units/rate), excluding code and
  URLs. At 300 Chinese units/minute and 200 English words/minute, the brief accepts
  2,101–3,600 Chinese units and 1,401–2,400 English words, displayed as 8–12 minutes.
- The six required section roles, two distinct evidence URLs, source locators,
  bilingual consistency, charts/markup validation and independent factual and final
  reviews remain required. Two URLs from one publisher do not establish independent
  verification; the planner is explicitly reminded of this boundary.
- Model call/retry budgets, collection limits, schedules and task enablement remain
  unchanged. One publication per day and existing provider circuits remain enforced.

## Verification and activation

Offline regression tests exercise the real temporary website publishing code with
synthetic model responses and no external source requests. New cases cover approved
bilingual brief publication and deduplication; source/review rejection; unsupported
targets; legacy long-only policy; outline budgets; length repair; watchdog recovery;
and post-humanizer repair followed by fresh factual review.

Activation uses rsync for the explicit code/config/test/document files and a
compare-and-swap update to only `daily-blog-agy-codex` in the live task database.
It retains an untracked configuration backup. The scheduler reads the changed
configuration without a service restart. Today's published article is not regenerated.
The tests establish workflow correctness, not a guarantee that future evidence or
model/provider availability will permit daily publication.
