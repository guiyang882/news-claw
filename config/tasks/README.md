# Tasks

每个 JSON 文件定义一个可独立管理的任务。`id` 应保持稳定，修改频率或查询条件不应更换任务 ID。`topic_ids` 中的值必须对应 `config/topics/*.json` 的 `id`。

news-claw 新任务的 `schedule` 使用五段 cron 表达式；`timezone` 使用 IANA 时区名，例如 `Asia/Shanghai`。从外部 systemd 导入的旧任务保留原始 `schedule`，并标记 `schedule_format`，不转换或近似改写。`collector` 保存来源类型、限流和运行归属等配置。

`scheduler_engine` 同步到 SQLite 的同名列，用于标明调度归属，例如 `news-claw` 或 `systemd`。该值表示指定/当前的调度引擎；实际服务是否正在运行仍需结合运行状态判断。

任务关联主题使用 JSON 中的 `topic_ids` 列表保存；SQLite 不再单独维护任务-主题关联表。

跨任务的启动时间应错开。任务可设置 `options.start_jitter_seconds`；采集器应遵守 `collector.request_policy` 中的主机并发、请求间隔、`Retry-After` 和退避限制，避免集中请求同一服务。

从 stocks-quant 镜像的任务设置 `scheduler_engine: "systemd"` 和 `enabled: false`，同时在 `collector.external_timer_active` 中记录观察到的旧 systemd 状态。这样 SQLite 会保留任务、频率和来源清单，但不会被未来的 news-claw 调度器重复启动。迁移状态见 `docs/stocks-quant-task-inventory.md`。
