# Tasks

每个 JSON 文件定义一个可独立管理的任务。`id` 应保持稳定，修改频率或查询条件不应更换任务 ID。`topic_ids` 中的值必须对应 `config/topics/*.json` 的 `id`。

新增任务可从 [config/templates/](../templates/README.md) 复制 crawl、codex、agy、publish、daily-blog、topic-summary 或网站维护模板；模板默认关闭，留在模板目录中不会导入数据库。

`task_type` 可标记 `crawl`、`codex`、`agy`、`publish` 或 `workflow`，同步到 SQLite 的同名列；没有显式类型时兼容旧 collector.type。Go 对所有类型使用相同的命令执行协议，类型用于管理展示。

`schedule` 使用五段 cron，`timezone` 使用 IANA 时区名，例如 `Asia/Shanghai`。结束后冷却任务使用 `schedule_format: completion_interval` 和 `schedule: "24h"`。迁移的原日历表达式保存在 `legacy_schedule`。

`execution.command` 是可执行程序和参数数组，支持 Python、Scrapy、Codex 包装程序、agy CLI 或其他前台命令。`collector` 和 `workflow` 由各自执行程序读取；Go 不把它们解释为 DAG 或自动触发规则。输入校验由执行脚本负责。

`scheduler_engine` 同步到 SQLite 的同名列，用于标明调度归属，例如 `news-claw` 或 `systemd`。该值表示指定/当前的调度引擎；实际服务是否正在运行仍需结合运行状态判断。

任务关联主题使用 JSON 中的 `topic_ids` 列表保存；SQLite 不再单独维护任务-主题关联表。

跨任务的启动时间应错开。任务可设置 `options.start_jitter_seconds`；采集器应遵守 `collector.request_policy` 中的主机并发、请求间隔、`Retry-After` 和退避限制，避免集中请求同一服务。

15 项定义中有 13 项启用，统一设置 `scheduler_engine: "news-claw"`。三个 Gemini 主题整理任务每日共五个槽位，整理后由 Codex medium 校验，通过后进入 knowledge 供博客选题使用，详见 [主题整理流程](../../docs/topic-summaries.md)。8 个旧 timer 停用。每日博客使用直接执行的 agy → Codex → humanizer → 最终复核 → 发布工作流，原两项博客 service 任务停用，配置与运行历史保留。其余旧 service 由 `collectors.legacy_service` 适配器执行。修改后运行 `make init`，常驻 engine 自动读取更新。

## 网站迁移后的任务内容

2026-10-13 的服务链路为 **Nginx → Next.js（quant-next-web，3000）→ Python 内容/API 服务（quant-web，8000）**。公开原生页面由 Next.js 提供，Python 不再维护第二套首页、博客或雷达 HTML。

全部存量任务与模板显式声明 `workflow.website_runtime` 与 `workflow.website_delivery`：前者供维护脚本读取服务、命令、端口与构建规则，后者说明产物归属。新主题采集只生成本地证据，原草稿任务只产生待审核稿；博客及已校验快照由 Python 内容服务读取，再经需要内部凭据的本机桥接接口交给 Next.js。凭据继续由受控环境提供，不写入任务 JSON。

内容更新仍只写运行时文件，不重启或构建前端。Python 代码更新用 `reload-content`；Next.js 服务重启用 `restart-frontend`，仅重启已经安装的构建。前端代码部署须在独立候选目录构建和检查，保留上一版静态 chunks，按部署说明停止前端、原子切换 `.next`、核对账号权限后启动并验证。维护脚本不替代这套构建发布步骤，也不能在运行目录直接构建。

旧 `reload-application` 动作已停用，需明确选择内容服务或前端。Nginx 配置仍先 `nginx -t` 再重载。三层检查涵盖 8000 的健康状态、3000 的真实博客 SSR 与本机 HTTPS 的同一页面，避免只测 Python `/healthz` 就误报前端正常。详见 [网站供稿与运维协议](../../docs/website-workflow.md)。
