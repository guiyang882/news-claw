# Tasks

每个 JSON 文件定义一个可独立管理的任务。`id` 应保持稳定，修改频率或查询条件不应更换任务 ID。`topic_ids` 中的值必须对应 `config/topics/*.json` 的 `id`。

新增任务可从 [config/templates/](../templates/README.md) 复制 crawl、codex 或 publish 模板；模板默认关闭，留在模板目录中不会导入数据库。

`task_type` 标记 `crawl`、`codex` 或 `publish`，同步到 SQLite 的同名列；没有显式类型时兼容旧 collector.type。Go 对所有类型使用相同的命令执行协议。

`schedule` 使用五段 cron，`timezone` 使用 IANA 时区名，例如 `Asia/Shanghai`。结束后冷却任务使用 `schedule_format: completion_interval` 和 `schedule: "24h"`。迁移的原日历表达式保存在 `legacy_schedule`。

`execution.command` 是可执行程序和参数数组，支持 Python、Scrapy、Codex 包装程序或其他前台命令。`collector` 由采集器解释；`workflow` 记录网站目录、输入输出和上下游任务，作为说明元数据，Go 不把它解释为 DAG 或自动触发规则。输入校验由执行脚本负责。

`scheduler_engine` 同步到 SQLite 的同名列，用于标明调度归属，例如 `news-claw` 或 `systemd`。该值表示指定/当前的调度引擎；实际服务是否正在运行仍需结合运行状态判断。

任务关联主题使用 JSON 中的 `topic_ids` 列表保存；SQLite 不再单独维护任务-主题关联表。

跨任务的启动时间应错开。任务可设置 `options.start_jitter_seconds`；采集器应遵守 `collector.request_policy` 中的主机并发、请求间隔、`Retry-After` 和退避限制，避免集中请求同一服务。

11 项任务统一设置 `scheduler_engine: "news-claw"`、`enabled: true`。8 个旧 timer 停用，现有 service 由 `collectors.legacy_service` 适配器执行。迁移状态见 `docs/stocks-quant-task-inventory.md`。修改后运行 `make init`，常驻 engine 自动读取更新。
