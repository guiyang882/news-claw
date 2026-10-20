# Gemini 主题整理与 Codex 校验

OpenCode DeepSeek 的独立试点配置已登记但默认关闭；2026-10-20 的真实摘要调用返回 403，原 AI 产品任务已恢复 Gemini。详见[试点结果与限制](opencode-topic-pilot.md)。

Go 调度器运行 `workflows.topic_summary`，执行 **本地证据 → Gemini 整理 → Codex 校验 → knowledge 入库**。同一执行协议支持这些任务，不增加数据库表或调度器专用分支。

## 启用的任务

以下时间为北京时间，每个槽位额外随机延迟 0–7 分钟。开始时间距对应主题采集约一小时，实际执行还受 `model-cli` 互斥和队列状态影响。

| 任务 ID | 内容 | 每日开始时间 |
| --- | --- | --- |
| us-china-controls-gemini-summary | 正式／拟议管制、日期、行业与公司影响 | 08:47 |
| ai-products-gemini-summary | Muse、Gemini Agent、GPT 的讨论与反馈边界 | 11:47、19:47 |
| physical-ai-space-gemini-summary | 机器人、物理 AI、Tesla、SpaceX、Rocket Lab | 15:17、23:17 |

加上原每日博客的写稿，Gemini 每日最多有 **6 个整理或写稿槽位**。没有足够材料、输入未变、供应方熔断或上一轮同输入失败时，不产生新的模型调用。它不是账号 token 配额，也不保证每天调用六次。

## 配置

模型、执行权限、推理强度、时间与材料预算直接保存在 `config/tasks/*gemini-summary.json`，复制示例为 [topic-summary.json](../config/templates/topic-summary.json)。修改后 `make init` 同步 SQLite，常驻 engine 自动读取。

- `workflow.writer`：`gemini-3.8-flash-high`，agy，900 秒，full 权限。
- `workflow.reviewer`：`gpt-6.1-sol`，medium，`service_tier: default`，420 秒，full 权限。
- `workflow.inputs`：回看 3 天、最多 16 个归属当前主题的文档、每条最多 1,400 字符；至少两个不同来源 URL。机器人／航天任务还读取明确配置公司的现有研究快照，标注快照日期和证据限制。
- `workflow.network_policy`：通常每轮两次 CLI 调用；`max_summary_revisions: 1` 允许一次 Codex 内容修订和独立复核，整轮最多四次。CLI／供应方失败无自动重试，不请求新网页；整轮超时 40 分钟。
- `execution.lock_group: model-cli`：与每日博客串行，供应方访问／额度拒绝沿用两类流程共享的持久熔断记录。

采集配置和来源请求限制仍在对应 crawl 任务中维护。整理任务使用已归档文件，不用 agy 绕过来源限制。

## 审核与产物

输入先按 `topic_links_json` 筛选，再应用数量上限，并核对规范化文件的内容哈希。未来日期、非法来源、归属错误或路径越界不能进入证据包。

Gemini 返回结构化的观察与逻辑、时间线、假设与替代解释、实体关系和证据缺口。程序兼容日期与完整 ISO 时间戳；只有月份日期时保留原表述、将精确日期留空，不补年份。从关系记录推导实体节点，把 RSS 引用标为线索，保留原响应与 `validated-summary.json`；标签不能替代正文中的具体归因。每项引用包含原来源 ID 和精确定位，缺少实际讨论样本时不能推出产品热度、情绪或采用率。Codex 校验全文、日期、引用、来源范围和证据边界；返回值必须绑定本轮材料和整理结果的哈希。

本地校验或 Codex 审核发现内容问题时，允许一次 Codex 修订，删去无依据的结论或补充具体媒体归因，再执行独立复核。缺少可用证据则返回不足；再次拒绝则停止，不做第二轮修订。只有明确通过校验的主题写入：

```text
data/knowledge/topics/<topic_id>/summaries/<task_id>-<input_fingerprint>.json
data/knowledge/topics/<topic_id>/summaries/<task_id>-<input_fingerprint>.md
```

JSON 保留完整 Gemini 响应、Codex 校验、原来源元数据及证据包路径，Markdown 便于阅读。`artifacts` 按主题登记版本、路径、输入指纹和证明哈希；`task_runs` 记录真实执行结果。缺少证据的子主题不覆盖旧产物。失败候选、证据正文和 CLI 日志只留在已被 Git 忽略的 `data/runs/<run_id>/`。

相同证据和模型配置的输入指纹只尝试一次，不因跨日而重复生成。失败／中断不自动重试；新材料形成新指纹后可以运行下一轮。修订整理规则或输出契约时需更新工作流 recipe 版本，使新规则有独立指纹。供应方拒绝不能通过换任务重试或清除熔断自动恢复。

若 Gemini 已成功、后续执行因代码或编辑问题停止，操作者可在任务 JSON 的 `workflow.manual_recovery` 显式设置 `run_id` 和当天 `day`，同步后手动入队。恢复须引用同任务的失败运行、当日同范围的证据包及原失败指纹；优先复用保存的 Codex 修订稿，其次复用 Gemini 响应，继续校验而不再次调用 Gemini。它保留旧运行和恢复审计，不清除供应方熔断。入队后移除该字段并重新同步；本轮快照保留恢复参数，后续定时任务使用正常配置。

## 供每日博客使用

每日博客读取近两天、最多五个主题的已审核整理，核验 JSON、Codex verdict 和原证据包的哈希，将整理结果作为选题参考，并把引用的原证据交给选题阶段。证据包缺失或内容变化时跳过对应整理。

选题完成后，写稿与复核只接收被选中的原始来源和证据，不把整理结果当成新的原始事实。网站仍通过原有的每日长文审核与发布流程更新；这些主题任务不直接发布文章。每日博客依旧北京时间 **07:30 加随机延迟，每天最多一篇**。内容文件更新无需重启或构建 Nginx／Next.js／Python 服务。

## 检查与手动运行

```bash
make init
bin/news-claw check
.venv/bin/python -m workflows.topic_summary --check --task ai-products-gemini-summary
bin/news-claw enqueue --task ai-products-gemini-summary
bin/news-claw runs --limit 20
```

`--check` 只读本地资料，不调用模型或创建正式知识产物。实际执行必须由 engine 启动，并绑定启用任务、本轮配置快照和 running 记录。


### 2026-10-14 输出截断修复

机器人与航天摘要曾在高推理档位耗尽输出额度，供应方返回 ERROR 与部分结构化内容。现将该任务配置为 CLI 实际支持的 `gemini-3.8-flash-low`；同一 Gemini 3.8 Flash 系列降低推理档位，不同时传入冲突的 high 模型别名与 low effort。摘要提示限制概述、观察、时间线、推论和关系的篇幅及数量；不截短来源定位符，不放松来源校验，也不接受部分响应。

writer 配置参与输入指纹，因此本次配置修复可通过新指纹验证，旧失败记录保留。失败调用及供应方使用量已进入共享 ModelRunner 审计，后续复核仍由 Codex 独立完成。
