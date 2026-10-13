# 任务模板

| 模板 | task_type | 示例执行程序 | 主要配置 |
| --- | --- | --- | --- |
| [crawl.json](crawl.json) | crawl | Scrapy 采集器 collectors.news | 来源、主题、请求预算、间隔、回看范围 |
| [codex.json](codex.json) | codex | 网站现有 Codex 草稿 service 的命令适配器 | 执行命令、输入输出、超时 |
| [agy.json](agy.json) | agy | 本机 agy CLI，使用已配置的模型 | 非交互提示词、模型选择、工作目录、超时 |
| [publish.json](publish.json) | publish | 网站现有审批后发布 service 的命令适配器 | 草稿输入、网站输出、校验要求 |
| [daily-blog.json](daily-blog.json) | workflow | workflows.daily_blog，多阶段博客工作流 | 候选选题、约20分钟大纲、Gemini写稿、Codex复核、humanizer、发布 |
| [website-maintenance.json](website-maintenance.json) | workflow | workflows.website_maintenance | Nginx / Next.js / Python 三层检查和分别维护 |

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

采集器支持 rss、atom、page 和 federal_register 来源；采集模板使用 NASA 公开 RSS。include_keywords 可筛选条目，来源的 topic_ids 可限定归属。请求之前复用缓存，跨来源间隔默认至少 10 秒，Google 来源另有共享限流和熔断状态。站点权限、请求预算和间隔应按来源设置。

## Codex 与发布任务的执行边界

Codex 模板以现有审核资料包生成草稿为例。workflow.codex 显式配置 model、reasoning_effort、service_tier 和 permissions，默认 gpt-6.1-sol / medium / default / full。旧 service 适配器传递本轮 task.json，网站执行程序实际读取这些参数；提示词与内容校验仍由执行程序维护。JSON 中的 task_type 供管理展示使用，Go 对它使用通用命令协议。使用 service 入口时需安装 [Codex 输入覆盖配置](../../deployment/README.md)。

Codex 和发布模板引用的 quant-blog-compose.service、quant-blog-daily.service 目前已停用，每日生产流程由 daily-blog-agy-codex 接管。模板保留旧草稿与人工批准入口作为示例；恢复前须明确审核方式并调整计划，避免与现有每日博客重复发布。

新增独立任务时，替换 execution.command、working_dir 和相关环境；同时移除旧 adapter、systemd_unit、recovery_command 等字段，按新执行程序设置超时、互斥和必要的恢复命令。collectors.legacy_service 只支持已经盘点的旧 service，不是自动创建 service 的工具。执行程序按照 [统一任务协议](../../docs/website-workflow.md) 读取本轮快照并输出 result.json。Codex 凭据由受控运行环境提供。

workflow.inputs、outputs、input_requirement 是说明元数据，不会自动检查文件或串联上下游。YYYY-MM-DD 由示例的执行程序按运行日期处理，Go 不展开它。独立脚本需自行校验输入和内容；发布沿用相应栏目的批准、校验和幂等规则，缺少输入或批准时记录等待或跳过。

## agy / Gemini 模板

agy.json 沿用同一 Go 命令协议、SQLite task_runs、日志、超时和互斥，不需要增加数据库表或 Go 专用执行分支。

本机已安装 /root/.local/bin/agy；通过本机 --help 核对了模板使用的 --print、--dangerously-skip-permissions、--disable-slash-commands、--output-format json 和 --print-timeout 参数。模板是处理本地知识材料的示例，提示词直接写在 execution.command 的 --print 参数中；新任务修改该参数及 topic_ids、工作目录、输入输出说明即可。

模板不指定 --model，继承 CLI 当前配置。启用前确认选择的是所需 Gemini 模型；需要固定模型时，在 command 参数数组中添加 --model 和本机有效的模型 ID。登录或 API 凭据由 CLI 的受控运行环境提供，不能放入任务 JSON。示例 lock_group=agy 让同组 agy 任务串行；它与网页采集的限流组独立。需要联网检索的独立任务还需接入相应来源预算、限流和熔断管理。

本机最初通过 deployment/news-claw-agy.conf 映射原 CLI 路径。用户要求所有模型任务 full 权限后，已安装排在末尾的 zz-full-access.conf，移除 home 与文件系统限制；agy 和 Codex 使用原账号及 profile，不移动安装文件或复制凭据。模板继续默认关闭，新增任务按上文设置内容和频率后启用即可。其他机器按 [部署说明](../../deployment/README.md) 先配置运行环境。

直接 CLI 的 JSON 输出被 engine 收入 data/runs/<run_id>/worker.log；task_runs.status 依据退出码记录执行成败。JSON 响应本身不会自动成为 NEWS_CLAW_RESULT_PATH 的 result.json、knowledge 产物或网站草稿。如果需要结构校验、业务状态和正式产物，使用包装脚本解析响应、校验内容，再写 result.json 和对应产物文件。CLI 按用户要求使用 full 权限，发布仍须通过内容校验；网站发布继续由相应 publish 任务处理。

## 共同字段

- 调度：id、task_type、scheduler_engine、enabled、schedule_format、schedule、timezone。
- 执行：execution.command、working_dir、timeout_seconds、lock_group；需要时添加 env、user、stop_grace_seconds 和 recovery_command。
- 整理归属：topic_ids、workflow；采集器另读取 collector 和 options。

默认使用五段 cron。需要结束后冷却时，改为 schedule_format=completion_interval、schedule="24h"，用 options.initial_delay_seconds 设置首次延迟。两个调度模式使用同一执行协议。

每日博客模板对应 [完整工作流](../../docs/daily-blog.md)，由执行脚本解释 workflow 中的模型、素材与发布参数。planner/reviewer 均显式配置 gpt-6.1-sol、service_tier=fast 和 reasoning_effort=null；null 保留模型默认，也可改为 medium/high 等。Go 仍使用通用命令协议。本机启用的 daily-blog-agy-codex 已接管每日发文，模板保持关闭。复制启用另一份前应调整发布目标或停用原任务，避免重复。

## Nginx / Next.js / Python 网站维护模板

维护模板默认关闭，执行动作为 `check`。它检查 Python 内容服务（8000）、Next.js 博客页面（3000）和 Nginx HTTPS 页面，HTTPS 连接回环地址并验证真实域名证书。页面检查同时覆盖 Next.js SSR 与内部内容桥接，检查命令、端口和页面标识都在 `workflow.website_runtime` 中配置，不读取或记录内部凭据。

Python 代码更新使用 `--action reload-content --execute`，HUP 仅发送给 `quant-web.service` 的主进程。重启已安装的 Next.js 构建使用 `--action restart-frontend --execute`，目标为 `quant-next-web.service`；这个动作不会执行构建或安装候选。入口配置更新使用 `--action reload-proxy --execute`，先检查 Nginx 配置再重载。旧 `reload-application` 已拒绝执行。缺少 `--execute` 时只输出计划；变更前检查三层状态，变更后限定等待服务就绪，失败停止，不自动回退旧入口。

前端代码发布须使用 `frontend_deployment` 所列的候选构建、smoke、原子切换及权限检查步骤；示例命令的候选路径需由操作者替换，Go 不展开这些说明字段。禁止覆盖运行中的 `.next`，保留旧静态 chunks 并复用受控环境中的桥接凭据。博客与新闻运行时数据更新不执行构建或服务操作。维护模板没有同步进 SQLite，也没有启用定时重启；完整命令见 [网站运维](../../docs/website-workflow.md#网站检查与分别维护)。
