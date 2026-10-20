# OpenCode DeepSeek 主题整理试点

## 当前状态：权限配置已修复（2026-10-20）

修正适配器后，真实证据输入已连续两次成功返回。正式 `ai-products-gemini-summary` 任务现使用 OpenCode DeepSeek 免费模型，仍由 Codex 审核；11:47、19:47 的北京时间调度及随机延迟保持不变。独立 `ai-products-opencode-pilot` 继续关闭，避免重复处理。

旧适配器同时设置 `OPENCODE_CONFIG_CONTENT.permission` 和 `OPENCODE_PERMISSION` 为 `{"*":"deny"}`。对照验证保留原失败运行的同一份证据、提示词、schema、模型和其余配置，只把权限策略改为 `{"*":"ask"}`，完整摘要成功返回并通过结构和引用定位校验。该差异指向权限配置与免费模型调用的兼容问题；服务端具体拒绝判定未公开，不能据此断言其内部校验机制。

`opencode run` 的默认非交互模式不带 `--auto` 时，会对权限请求自动回复 `reject`，不会等待人工输入；这是 CLI 1.19.3 的原生行为，并没有放开工具执行或修改客户端身份。模型仍被要求不用工具，适配器仍拒收任何工具调用事件。参见[官方版本源码的 permission.asked 分支](https://raw.githubusercontent.com/anomalyco/opencode/v1.19.3/packages/opencode/src/cli/cmd/run.ts)。

| 验证 | 结果 | 耗时 | CLI 报告费用 |
| --- | --- | --- | --- |
| 原失败证据包、仅修改权限策略 | 完整摘要 `ready`，本地 JSON / 引用校验通过 | 48.140 秒 | 0 |
| Go engine 正式运行 `041415d7403553905fc5fe6a84aaec97`，最新 16 条来源 | 正常完成，返回 `insufficient_evidence` | 8.765 秒 | 0 |

第二轮材料缺少实际讨论样本、基线与原始反馈；没有生成或入库无证据的热度结论。业务“证据不足”与接口失败分开记录。第一轮输出另行接受 Codex 独立质量审核，审计文件在 `playground/opencode-config-fix/`。两次成功只是初步可用性验证，尚不能证明多日稳定性。

第一轮质量审核结果：引用 ID、定位和日期通过，但初审拒绝了超出标题证据的讨论/试用推断、Accenture 合作关系表述，以及缺失的样本偏差边界。按既有流程由 Codex 修订一次，随后独立复核通过（`approved: true`、`issues: []`）。这是评估材料，未作为新知识写入生产库。初审 18.623 秒、修订 33.915 秒、复核 9.217 秒；这些 Codex 调用不包含在上表 DeepSeek 的费用中。不能把“CLI 费用为零”写成整条流程零成本。

旧熔断在用户明确要求修复配置后解除，原内容和理由保存在 `playground/opencode-config-fix/operator-reset.json`。当天计数保留了失败调用和对照验证，未清空每日预算。

## 首次试点结果（18:17，历史记录）

选择已有的 AI 产品反馈整理作为试点：输入为本地缓存的公开材料，输出为带引用的结构化摘要，Codex 仍独立审核。它不直接发布网站文章。

**普通交互和短 `OK` 调用成功，不等于真实摘要工作流已经可用。** 在 Go engine 中执行完整任务时，OpenCode 返回 403 / `FreeTierError`，没有生成摘要，无法评估内容质量或长期稳定性。

| 项目 | 本次实际结果 |
| --- | --- |
| 原任务 | `ai-products-gemini-summary` |
| 真实运行 ID | `349dbe9add4fddc390e9dca8c3964974` |
| 时间 | 北京时间 2026-10-20 18:17:32–18:17:37 |
| 输入 | 16 条已缓存来源、16 条证据；没有新网页抓取 |
| 模型 | `opencode/deepseek-v4.1-flash-free`，OpenCode 1.19.3 |
| 耗时 | 5.105 秒 |
| 结果 | 403 / `FreeTierError`；CLI 退出 1 |
| 请求追踪 | `01a158d1-0a09-71cf-8a1a-85ea638f5c88` |
| 后续审核与入库 | 未执行，没有可审核的摘要 |
| 自动重试 | 工作流未重试；返回 `isRetryable=false` |

这次使用标准 Build agent，没有 `--pure`、自定义系统提示或替换 XDG 目录；通过任务级配置禁止工具、限制免费模型，并从 stdin 传入证据和 JSON Schema。输入长度、工具权限、进程环境与短测试均不同，尚不能把 403 唯一归因于某一个因素，更不能直接认定新加坡网络出口被封。

原任务的配置、模型与 SQLite 定义已恢复为原来的 agy / Gemini，仍按北京时间 11:47、19:47 加 0–7 分钟随机延迟运行。失败记录保留。没有变更博客写稿模型、网站服务或其他任务。

## 保留的适配与任务

`workflows/opencode_writer.py` 接入现有 `ModelRunner`，仅在 `workflow.writer_provider: opencode` 时生效。正式任务复用原主题、证据过滤、去重和 Codex 审核流程；独立 `ai-products-opencode-pilot` **默认关闭**，可通过 news-claw 的任务列表查看。

- 限定免费模型 ID，无其他模型或付费回退。
- 每天最多 3 次 OpenCode 工作流调用（包括失败和手动调用），按北京时间计日并持久化。使用共享 `model-cli` 互斥和至少 10 秒间隔。
- 单次超时 600 秒，进程上限 615 秒。工作流不对 OpenCode 自动重试。
- 使用全局 `ask` 配合非交互自动拒绝；不传 `--auto`、`--pure` 或自定义系统提示。禁用分享与自动升级，保留标准 OpenCode agent；收到工具事件时拒绝入库。
- 只接收完整单轮 JSON；拒绝错误事件、截断、缺失结束事件、多轮调用、非法 schema 和非零/缺失费用记录。
- 401 / 403 / 429 打开独立 `opencode.blocked.json` 熔断；不影响 agy / Codex 的熔断状态。
- 保留每次调用的模型、时间、状态、用量、CLI 报告费用、会话 ID；失败保留原始事件，不把失败费用当作零。

任务文件仍沿用主题工作流的 `01-agy-summary` 历史目录名称，实际供应方以 `call.json` 的 `provider` / `model` 为准。后续若通过验证，Codex 审核明确通过才写入主题知识库；正式博客仍有自己的事实与发布审核。

## 后续验证标准

未来若再发生访问拒绝，应先定位、再显式评估和恢复熔断。不能以改变请求身份、反复清空熔断或换付费模型来掩盖失败。不要同时启用原任务与试点长期重复处理相同材料。

验证至少覆盖不同来源包的完整摘要、来源 ID / locator 校验、Codex 初次通过率和修订情况；另需观察多日计划执行的成功率、延迟、用量、429 / 403 与截断情况。保留失败和修复后的成功结果，不能只凭两次调用宣称“稳定可用”。

只读预览（不调用模型）：

```sh
bin/news-claw tasks
/mnt/quant/strategies/stocks-quant/web/.venv/bin/python \
  -m workflows.topic_summary --check --task ai-products-opencode-pilot
```

## 验证记录

OpenCode 适配的 10 项测试、主题摘要的 21 项测试通过。扩大执行至 92 项测试时，90 项通过；两项原有博客测试失败，在改动前的 HEAD 代码上同样复现：

- `test_budget_failure_after_approved_revision_resumes_exact_final_review`
- `test_discovered_page_is_retained_beyond_feed_window_and_not_truncated`

离线测试不访问外部模型。真实调用的完整证据保存在 `data/runs/349dbe9add4fddc390e9dca8c3964974/`；数据库、源材料和原始调用日志不纳入本次提交。

CLI 与权限配置参考：[OpenCode CLI](https://opencode.ai/docs/cli/)、[Permissions](https://opencode.ai/docs/permissions/)。
