# OpenCode free-model evaluation — 2026-10-20

**Latest result:** standard OpenCode 1.19.3 interactive and non-interactive invocations on Singapore both successfully returned `OK` with `opencode/deepseek-v4.1-flash-free` and reported cost 0. Earlier isolated probe failures below remain historical evidence, not the current availability conclusion. See the final follow-up for commands and scope.

**Production-workflow follow-up:** the later 18:17 China-time AI-products summary pilot (16 cached sources, text-only permissions and JSON contract) returned 403 / FreeTierError in 5.105 seconds. The original agy task was restored; the separate OpenCode pilot is registered but disabled with its circuit retained. Minimal CLI connectivity remains verified; actual summary quality and sustained stability are not. See [pilot results and controls](opencode-topic-pilot.md).

## Installation and scope

Installed the official npm package `opencode-ai@1.19.3` on the Singapore ECS under `/opt/opencode/1.19.3`; `/usr/local/bin/opencode` points to its CLI. `opencode --version` reports `1.19.3`. No existing OpenCode command was present. No web or news-claw service restart, task schedule change, credential migration or paid-provider setup was performed.

Official references checked:

- https://github.com/anomalyco/opencode/releases/tag/v1.19.3
- https://opencode.ai/docs/ (npm package installation)
- https://opencode.ai/v2/docs/console/models/#free-models
- https://opencode.ai/docs/permissions/
- https://opencode.ai/docs/config/

The model catalogue lists `opencode/deepseek-v4.1-flash-free` as limited-time free. This is distinct from paid `deepseek-v4.1-flash`. No fixed RPM/TPM guarantee was found in the reviewed official model documentation. Free pricing must not be treated as unlimited throughput or guaranteed future availability.

## Actual test

One synthetic connectivity request was made using the official CLI:

`opencode run --pure --agent probe --model opencode/deepseek-v4.1-flash-free --title 'Free model connectivity probe' --format json ...`

The probe used a dedicated empty working directory, separate XDG config/data/cache/state, no inherited API credentials, only the OpenCode provider, the same free model for auxiliary work, disabled sharing/auto-updates, and denied all agent tools. No repository or private document content was sent. No paid fallback was configured.

Result: exit 1 after 6.6 seconds. The API returned HTTP 403, `FreeTierError`, `isRetryable=false`: “OpenCode's free tier can only be used from within OpenCode.” The message contradicts the fact that the request used the official CLI; the precise cause is unconfirmed. Request log ID: `01a15826-2d1b-71bb-b768-13baaab52840`.

No retry was attempted after denial. Do not spoof client headers, rotate identities/IPs, repeatedly probe, or attach this provider to scheduled production work while access is unresolved. A documented supported resolution from OpenCode is needed before a new test.

Local server audit artifacts: `/mnt/quant/news-claw/playground/opencode-evaluation-20261020/` (probe config, event output and result). The test runner is `/mnt/quant/news-claw/playground/opencode-probe-20261020.py`. Do not rerun it merely to clear this denial.

## agy findings and integration decision

Reviewed up to 1,500 recent task runs created since October 18, plus recent service logs and blog provider circuit files. The saved result errors inspected did not show 429, rate-limit/quota exhaustion, or token-output truncation. October 20's writer failure was metadata overflow followed by a humanizer-review failure, subsequently repaired and published; it was not an observed token-rate limit.

Therefore no blanket reduction or provider switch was applied to active tasks. Existing cache reuse, serialized model-cli work, provider circuits and budgets remain in force. No trading or paused data-download tasks were enabled.

If supported free access becomes available, the first candidate workloads are cached-source extraction/topic summaries and draft generation. Keep factual/final reviews on the existing reviewer and preserve JSON validation, source binding and publication gates. Validate representative bilingual long output before routing real drafts. Use serial requests, at least 10 seconds apart, explicit per-run/day caps, stop on 429/denial, and no paid fallback. Connectivity alone is not sufficient to enable automatic daily publication.

## Follow-up: connection state and user-provided Jev example

`opencode auth list` reports zero saved credentials. Starting the supported `opencode auth login --provider opencode` flow (the CLI counterpart of `/connect`) prompts for an API key from `https://opencode.ai/auth`. The prompt was cancelled without adding credentials. This establishes only that no account is connected; it does not prove that every free model requires authentication or that authentication fixes the earlier DeepSeek 403.

At the user's explicit request, ran their separate Jev example once on Singapore, without an Authorization header:

```sh
curl https://opencode.ai/inference/systemone/v1/systemone \
  -H 'Content-Type: application/json' \
  -d '{"model":"jev-1.13-free","state":"生产服务持续返回 500 错误。","questions":{"is_urgent":{"type":"noul","instructions":"是否需要紧急处理？"}}}'
```

Result: HTTP 200 in 0.802345 seconds, with 292 input tokens and 23 output tokens:

```json
{"model":"jev-1.13-free","answers":{"is_urgent":{"type":"noul","noul":0.93}},"usage":{"input_tokens":292,"output_tokens":23}}
```

Jev's anonymous structured-decision endpoint is therefore usable in this test. The example state was synthetic, not a report of an actual production outage. The output is a model judgment, not a verified incident probability. This is a different model and protocol from DeepSeek's chat/completions endpoint; it neither confirms nor disproves that separate free-tier access restriction. Jev supports typed questions and scores rather than long-form article generation (https://opencode.ai/v2/docs/console/models/#jev), so it was not substituted for the blog writer. No login is needed to reproduce the successful Jev test as observed today; broader availability and quotas remain unverified.

Prior installation/evaluation commit `041cf00` was already pushed; the local branch and origin/main matched before this follow-up. Preserve the successful Jev request/response under the evaluation playground rather than repeatedly probing either provider.

## Follow-up: standard DeepSeek invocations succeed

At the user's request to reproduce their exact startup command, used the existing Singapore environment and standard OpenCode configuration, without `--pure`, isolated XDG directories, or custom agent configuration:

```sh
opencode -m opencode/deepseek-v4.1-flash-free
```

Entered `Do not use any tools or read files. Reply only OK.` The standard Build agent returned `OK`; the UI reported 5.7 seconds. Exported session `ses_ea756b6a2ffeVZztMUrDbuelFp` confirms model `deepseek-v4.1-flash-free`, cost 0, 8,208 total tokens (including 1,664 cached input tokens), 2 output tokens, and no tool calls. Exited the TUI normally.

After more than ten seconds, checked the standard non-interactive invocation once:

```sh
opencode run -m opencode/deepseek-v4.1-flash-free --format json \
  --title "Standard CLI connectivity check" \
  "Do not use tools or read files. Reply only OK."
```

This also exited 0 and returned `OK`, with 7,825 total tokens, 2 output tokens, and cost 0. Session: `ses_ea75291e1ffeb3dylyK7ku0HkZ`. Evidence: `playground/opencode-recheck-20261020/tui-success.json` and `run-standard.jsonl`.

Thus the model is currently usable on Singapore through both normal invocation modes. No login, credentials, client-header edits, proxy changes or software upgrade were applied for these successful tests. The earlier isolated default-Build probe still returned 403 at 16:42 China time; these later tests changed both configuration context and time, so the exact cause is not isolated. Do not claim that Singapore egress is blocked, that `/connect` is required, or that the custom agent alone caused the rejection.

These are minimal connectivity checks, not validation of sustained quota, bilingual article quality or production task integration. Scheduled tasks and provider routing remain unchanged. Use normal supported invocation as the baseline for future controlled evaluation, retaining existing serialization, budgets and stop-on-denial behavior.
