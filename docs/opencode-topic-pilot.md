# OpenCode DeepSeek 主题整理试点

## 当前结论（2026-10-20）

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

`workflows/opencode_writer.py` 接入现有 `ModelRunner`，仅在 `workflow.writer_provider: opencode` 时生效。单独注册的 `ai-products-opencode-pilot` **默认关闭**，可通过 news-claw 的任务列表查看；它复用原主题、证据过滤、去重和 Codex 审核流程，不会自动绕过当前拒绝。

- 限定免费模型 ID，无其他模型或付费回退。
- 每天最多 3 次 OpenCode 工作流调用（包括失败和手动调用），按北京时间计日并持久化。使用共享 `model-cli` 互斥和至少 10 秒间隔。
- 单次超时 600 秒，进程上限 615 秒。工作流不对 OpenCode 自动重试。
- 禁用工具操作、分享与自动升级；保留标准 OpenCode agent。记录实际收到的工具事件时拒绝入库。
- 只接收完整单轮 JSON；拒绝错误事件、截断、缺失结束事件、多轮调用、非法 schema 和非零/缺失费用记录。
- 401 / 403 / 429 打开独立 `opencode.blocked.json` 熔断；不影响 agy / Codex 的熔断状态。
- 保留每次调用的模型、时间、状态、用量、CLI 报告费用、会话 ID；失败保留原始事件，不把失败费用当作零。

任务文件仍沿用主题工作流的 `01-agy-summary` 历史目录名称，实际供应方以 `call.json` 的 `provider` / `model` 为准。后续若通过验证，Codex 审核明确通过才写入主题知识库；正式博客仍有自己的事实与发布审核。

## 后续验证标准

先解决实际任务的访问拒绝，再显式评估和恢复熔断。不能以改变请求身份、反复清空熔断或换付费模型来掩盖失败。不要同时启用原任务与试点长期重复处理相同材料。

验证至少覆盖不同来源包的完整摘要、来源 ID / locator 校验、Codex 初次通过率和修订情况；另需观察多日计划执行的成功率、延迟、用量、429 / 403 与截断情况。当前只有一次真实工作流失败，不能宣称“稳定可用”。

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
