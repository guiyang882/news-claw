# 任务模板

| 模板 | task_type | 示例执行程序 | 主要配置 |
| --- | --- | --- | --- |
| [crawl.json](crawl.json) | crawl | Scrapy 采集器 collectors.news | 来源、主题、请求预算、间隔、回看范围 |
| [codex.json](codex.json) | codex | 网站现有 Codex 草稿 service 的命令适配器 | 执行命令、输入输出、超时 |
| [agy.json](agy.json) | agy | 本机 agy CLI，使用已配置的模型 | 非交互提示词、模型选择、工作目录、超时 |
| [publish.json](publish.json) | publish | 网站现有审批后发布 service 的命令适配器 | 草稿输入、网站输出、校验要求 |

模板均为完整 JSON，默认 enabled=false。初始化只读取 config/tasks/*.json，模板留在本目录时不会进入 SQLite 或被调度。文件是复制用的配置示例，没有变量替换、继承或自动渲染机制。

## 使用

```bash
cp config/templates/crawl.json config/tasks/my-topic-daily.json
```

1. 修改 id、name 和 description；建议文件名与 id 一致。任务 ID 在后续调优中保持稳定。
2. 修改 topic_ids，确保主题已定义在 config/topics/ 中。
3. 配置实际来源或 execution.command，并核对 workflow 的输入输出。
4. 设置与现有任务错开的 schedule。采集模板另有最多 5 分钟启动随机延迟和请求限流。
5. 将 enabled 改为 true 后运行 make init。常驻 engine 自动读取 SQLite 中的新配置；bin/news-claw check 可只读检查同步后的调度配置。

采集器支持 rss、atom 和 page 来源；请求之前复用缓存，Google 来源共享限流和熔断状态。站点权限、请求预算和间隔应按来源设置。

## Codex 与发布任务的执行边界

Codex 模板以现有审核资料包生成草稿为例，提示词、模型调用和内容校验仍由 stocks-quant 的 web.blog_compose 执行程序维护。JSON 中的 task_type 供管理展示使用，Go 对它使用通用命令协议。

Codex 和发布模板引用的 quant-blog-compose.service、quant-blog-daily.service 已由现有生产任务调度。复用同一 service 时应修改已有任务，或停用原配置后替换；同一执行入口只保留一份启用的计划。

新增独立任务时，替换 execution.command、working_dir 和相关环境；同时移除旧 adapter、systemd_unit、recovery_command 等字段，按新执行程序设置超时、互斥和必要的恢复命令。collectors.legacy_service 只支持已经盘点的旧 service，不是自动创建 service 的工具。执行程序按照 [统一任务协议](../../docs/website-workflow.md) 读取本轮快照并输出 result.json。Codex 凭据由受控运行环境提供。

workflow.inputs、outputs、input_requirement 是说明元数据，不会自动检查文件或串联上下游。YYYY-MM-DD 由示例的执行程序按运行日期处理，Go 不展开它。独立脚本需自行校验输入和内容；发布沿用相应栏目的批准、校验和幂等规则，缺少输入或批准时记录等待或跳过。

## agy / Gemini 模板

agy.json 是第四种执行模板，沿用同一 Go 命令协议、SQLite task_runs、日志、超时和互斥，不需要增加数据库表或 Go 专用执行分支。

本机已安装 /root/.local/bin/agy；通过本机 --help 核对了模板使用的 --print、--mode plan、--sandbox、--disable-slash-commands、--output-format json 和 --print-timeout 参数。模板是处理本地知识材料的示例，提示词直接写在 execution.command 的 --print 参数中；新任务修改该参数及 topic_ids、工作目录、输入输出说明即可。

模板不指定 --model，继承 CLI 当前配置。启用前确认选择的是所需 Gemini 模型；需要固定模型时，在 command 参数数组中添加 --model 和本机有效的模型 ID。登录或 API 凭据由 CLI 的受控运行环境提供，不能放入任务 JSON。示例 lock_group=agy 让同组 agy 任务串行；它与网页采集的限流组独立。需要联网检索的独立任务还需接入相应来源预算、限流和熔断管理。

当前 deployment/news-claw.service 使用 ProtectHome=true，本机的 /root/.local/bin/agy 及 /root 下的登录资料不能被该常驻进程访问。因此本模板保持关闭；启用前需配置可执行程序和必要登录目录的受控可访问路径，或通过有正确运行环境的独立执行适配器调用。修改 task_type 或 execution.user 不会解除 service 的文件系统隔离。前台 engine 使用相同账号时仍需先核对 CLI 登录与模型配置。本次未发起模型请求，也未修改线上服务权限。

直接 CLI 的 JSON 输出被 engine 收入 data/runs/<run_id>/worker.log；task_runs.status 依据退出码记录执行成败。JSON 响应本身不会自动成为 NEWS_CLAW_RESULT_PATH 的 result.json、knowledge 产物或网站草稿。如果需要结构校验、业务状态和正式产物，使用包装脚本解析响应、校验内容，再写 result.json 和对应产物文件。提示词的输入限制与 CLI plan/sandbox 设置不能替代发布校验；网站发布继续由相应 publish 任务处理。

## 共同字段

- 调度：id、task_type、scheduler_engine、enabled、schedule_format、schedule、timezone。
- 执行：execution.command、working_dir、timeout_seconds、lock_group；需要时添加 env、user、stop_grace_seconds 和 recovery_command。
- 整理归属：topic_ids、workflow；采集器另读取 collector 和 options。

默认使用五段 cron。需要结束后冷却时，改为 schedule_format=completion_interval、schedule="24h"，用 options.initial_delay_seconds 设置首次延迟。两个调度模式使用同一执行协议。
