# Go 调度器与 Scrapy

Go 管理任务计划和子进程，Scrapy 管理网页请求，SQLite 保存状态与运行记录。第一版采用 Linux 单主机、单调度进程，默认最多两个 worker；共享 `web-fetch` 限流组的任务串行执行。

## 安装与命令

需要 Go 1.24+、C 编译器（SQLite 驱动使用 CGO）和 Python 3.11+。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
make init
make build
make check

# 只读查看，不创建计划、不发起抓取。
bin/news-claw tasks
bin/news-claw runs --limit 20

# 保存未来计划，不执行。
bin/news-claw plan

# 前台常驻，SIGINT/SIGTERM 会停止并收尾子进程。
bin/news-claw serve --workers 2 --poll 5s

# 立即入队，跳过启动随机延迟，仍遵守请求限流。
bin/news-claw enqueue --task us-china-export-controls-daily

# 单次执行当前已到期队列；延迟尚未到期的运行留在队列中。
bin/news-claw serve --once
```

所有命令支持 `--root /mnt/quant/news-claw` 和 `--db data/db/news.sqlite3`。已有常驻进程时使用 enqueue 即可。plan 与 serve 共用单实例锁。

JSON 是定义来源，修改后运行 `make init` 同步，engine 每 5 秒重新读取数据库。直接修改 DB 配置会在下次初始化时被覆盖；新增调度状态不会被覆盖。暂停/恢复通过 JSON 的 enabled 字段同步：排队任务取消，正在运行的任务完成后停止再次调度。当前不支持 YAML。

## 任务执行配置

```json
{
  "id": "us-china-export-controls-daily",
  "name": "中美进出口管制政策追踪",
  "task_type": "crawl",
  "scheduler_engine": "news-claw",
  "enabled": true,
  "schedule_format": "cron",
  "schedule": "15 7 * * *",
  "timezone": "Asia/Shanghai",
  "execution": {
    "command": [".venv/bin/python", "-m", "collectors.news"],
    "working_dir": ".",
    "timeout_seconds": 1800,
    "lock_group": "web-fetch"
  },
  "options": {"start_jitter_seconds": 300}
}
```

命令使用参数数组，直接启动程序。以 `.` 开头的 executable 路径相对于 repo 根目录；其他相对程序名从 PATH 查找。working_dir 相对于根目录，亦可使用绝对路径。可通过 env 传入环境变量，engine 的 NEWS_CLAW_* 参数优先。可选 execution.user 保留旧 Linux 执行账号，切换用户需要权限及对应目录的访问权限；新采集任务建议与 engine 使用同一账号。

`task_type` 仅用于管理展示，Go 使用统一执行协议，既可运行采集器，也可运行 Codex 包装脚本或网站发布脚本；采集、来源和发布校验留在执行程序。`workflow` 是输入输出说明元数据，不执行 DAG 调度，见 [网站工作流](website-workflow.md)。

支持五段 cron。`schedule_format: completion_interval` 配合 `schedule: "24h"` 表示上轮结束后至少 24 小时再次执行，首次使用 options.initial_delay_seconds（默认 0），迁移时可用 options.first_run_at 设置原任务的 UTC 冷却截止时间。这个模式保留旧 OFR timer 的结束后冷却语义。

## 状态与恢复

保持 6 张表。migration 004 添加：

| 表 | 新字段/约束 | 用途 |
| --- | --- | --- |
| tasks | next_run_at | 下一个未入队的计划时间，UTC |
| tasks | schedule_fingerprint | 配置改变时重建计划 |
| task_runs | run_after | 已持久化的实际允许启动时间，包含随机延迟 |
| task_runs | task_id + scheduled_for 唯一索引 | 同一计划槽位不会重复入队；手动运行的 scheduled_for 为 NULL |

队列复用 task_runs 的 queued/running/succeeded/failed/cancelled 状态。metadata_json 保存触发方式、任务配置和执行参数快照、限流组、PID、采集统计。每轮在 data/runs/<run_id>/ 保存 worker.log、task.json 和采集器返回的 result.json。

通过 SQLite 写事务原子领取任务，复查启用状态、调度归属和同任务/同限流组互斥。首次接管或配置改变时从未来计划开始；已有计划在停机期间错过多轮时合并为一轮。随机延迟只生成一次，重启后继续使用。

engine 使用 DB 旁的 flock 锁，子进程继承锁描述符：engine 意外退出后，新进程会等旧 worker 退出，避免重复执行。正常超时或停止会结束整个子进程组。执行程序必须以前台方式运行，不能自行 daemonize；继承锁的孤立 worker 未退出时会阻止新 engine 启动。

恢复时先执行旧运行快照中的 `execution.recovery_command`（如果配置了），以清理进程组外的工作；超时使用 recovery_timeout_seconds，默认 120 秒。清理失败会停止启动，保留 running 记录与互斥。清理成功后旧 running 记录标为 failed，注明结果未知，检查输出后再决定手动重试；未来周期继续执行。第一版不自动重试整轮，避免外部写入/发布被重复执行。

超时或正常停止使用 stop_grace_seconds（默认 5 秒）等待程序收尾，再强制结束进程组。超时、执行器异常退出且没有结果，或 result.json 声明 recovery_required 时，也先运行恢复命令；清理失败保持 running 与来源互斥，engine 停止并在重启时重新清理。旧 service 适配器配置 115 秒以等待原服务停止；中断恢复配置通用 systemctl stop 命令，Go 不识别 service 类型。

## Scrapy 采集范围

三个新闻任务接入 Federal Register API、Google AI 博客、OpenAI、Hacker News、NASA 与 NVIDIA，共 6 个来源。sources 支持 rss、atom、page 和 federal_register；网页类型保存 HTML 和基础正文抽取结果，federal_register 解析官方 API 的公告列表与摘要。

RSS 保存标题、链接、发布时间和 feed 提供的正文或摘要，尚未跟进下载文章全文。source.include_keywords 按词或短语边界筛选条目；source.topic_ids 可以指定任务主题的子集，避免将航天公告同时标为机器人材料。Muse 产品消歧、讨论代表性、关注度指标与政策影响判断仍需后续整理，Hacker News 首页 RSS 仅代表部分讨论。

2026-10-11 排查发现 Google News 的 robots.txt 不允许当前客户端访问 /rss/search，原 7 个查询已从启用任务中移除；采集模板改用 NASA 公开 RSS。robots 检查保持启用。复核订阅用途后，小时级旧 Google RSS 任务也已暂停，详见 [访问核查](operations/2026-10-11-google-news-access.md)。Rocket Lab 投资者网站的权限检查返回 HTTP 403，已停止该来源并记录熔断；当前航天来源不保证覆盖每家公司的公告。

`metadata_json.result.failure_details` 区分 `robots_denied`（端点尚未下载）、`http_access_denied`（401/403）与 `http_rate_limited`（429），记录实际端点与 HTTP 状态；robots 拦截的端点 HTTP 状态为空。已有失败记录保留原始结果。

原始响应按来源/日期/哈希归档到 data/raw，结构化条目存入 data/normalized 与 documents。内容去重，重复条目合并主题关联。HTTP 缓存 30 分钟，命中缓存不消耗网络额度。

每轮最多 12 个网络请求，包含 robots.txt 和重定向；每域名最多一个并发，普通来源间隔至少 10 秒，Google 服务共享至少 45 秒间隔。min_interval_seconds_global 默认 10 秒，在不同域名和任务之间共享请求间隔；本地测试显式设为 0。跨轮次请求时间和熔断状态保存在 data/runs/request-policy，通过文件锁共享。遵守 robots.txt。

失败时，task_runs.error 同时保留执行程序 result.json 中的 error 或 errors 摘要，日志保留完整信息，避免数据库仅显示 exit status 1。

遇到 401/403/429 停止来源并持久化熔断，记录 Retry-After，不自动重试或恢复。判断可恢复后显式清除熔断（保留请求间隔）：

```bash
.venv/bin/python -m collectors.news --reset-source google
```

其他来源使用 hostname 作为来源键。手动恢复后仍遵守 Retry-After 的剩余等待时间。HTTP 错误、无效 feed、解析/存储错误和额度耗尽会使本轮失败，已完成文档保留。

## 旧任务与线上服务

2026-10-10 将 8 个旧 timer 的调度交给 Go，连同 3 个新任务共 11 项。所有任务均为 news-claw/enabled，旧 timer disabled/inactive，news-claw.service 常驻且开机启动。原日历保存在 legacy_schedule，迁移前最后一次 service 的结果导入 task_runs，标记 engine=systemd；这是最后一次结果快照，不是全部历史日志。

旧任务由 collectors.legacy_service 执行原 oneshot service。service 保留实际安装的账号、Codex HOME/环境、文件沙箱、原数据路径、缓存、审计和锁；离线发布仍使用 PrivateNetwork 及哈希绑定人工批准。systemd 用于进程托管与旧任务执行隔离，11 项时间计划由 Go 管理。Go 调度层没有 systemd 专用代码。

已暂停的小时 RSS 保留每小时第 5 分钟加最多 4 分钟随机延迟的配置，旧脚本通过 drop-in 限制为每分钟 1 请求。RSS 适配器与新 Scrapy 任务共用 web-fetch 互斥、Google 来源边界间隔与熔断检查；新任务也读取旧脚本的 Google 熔断文件。旧脚本内部保持自己的缓存、锁和熔断；任务结束后保守预留至少 60 秒再允许新请求。两个熔断文件恢复时需分别核对，清理一个不会解除另一个；恢复 Google RSS 还需先满足访问与用途许可条件。

迁移脚本默认仅预览，`--apply` 检查旧任务未运行，备份配置和 SQLite，停用旧 timer，安装 engine service/RSS drop-in，同步 JSON 和计划，再启动服务。失败会恢复原配置、数据库、unit 和 timer 状态。备份保存在忽略提交的 data/runs/handoff-*。已经迁移时不要重复 apply。

```bash
python3 scripts/migrate_systemd.py           # 初次迁移前预览
python3 scripts/migrate_systemd.py --apply   # 初次接管
systemctl status news-claw.service
journalctl -u news-claw.service --since today
bin/news-claw tasks
bin/news-claw runs --limit 20
```

迁移不修复原业务脚本的既有失败。最近的 news-analysis、Optimus 供应链和科技史任务已有失败结果，已如实导入；不能据此宣称每项业务都能成功生成内容。博客 business_status 可区分缺输入、等待批准与实际发布。

## 测试

`make test` 运行 Go 并发/恢复测试与 Python 端到端测试。覆盖时区、持久化随机延迟、补跑合并、结束后间隔、领取互斥、暂停与归属、恢复、超时，以及真实 Go → Scrapy → 本地 HTTP 的归档、去重、主题合并、缓存、跨任务请求间隔、熔断和预算。测试使用临时目录，不访问线上来源。
