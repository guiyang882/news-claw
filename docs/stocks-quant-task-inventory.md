# stocks-quant 旧定时任务盘点

盘点与迁移日期：2026-10-10（北京时间）。检查了 `/mnt/quant/strategies/stocks-quant/AGENTS.md`、主机实际安装的 service/timer、运行说明与最近结果。随后将 8 个旧 timer 的调度交给 Go。旧运行数据保持原路径，没有手动发起线上抓取、Codex 或发布。

| 旧任务 | systemd 频率 | 性质 | 数据库登记 |
| --- | --- | --- | --- |
| `quant-news-refresh.timer` | 每小时，随机延迟最多 4 分钟 | Google News RSS：Rocket Lab、SpaceX、Tesla；每批最多 3 请求 | `stocks-quant-market-news-refresh`，映射到机器人、物理 AI、太空竞赛 |
| `quant-news-analysis.timer` | 每 3 小时于第 10 分钟，随机延迟最多 2 分钟 | 处理已有新闻时间线，不访问来源网页 | `stocks-quant-market-news-analysis` |
| `quant-optimus-supply-review.timer` | 周一 09:20，随机延迟最多 20 分钟 | Tesla Optimus 供应商复核，每批最多 6 个新来源页，成功快照冷却 7 天 | `stocks-quant-optimus-supplier-review` |
| `quant-company-pulses-review.timer` | 周一、周四 10:10，随机延迟最多 20 分钟 | Rocket Lab 和 SpaceX 深度复核，每批最多 6 个新来源页，冷却 3 天 | `stocks-quant-company-pulses-review` |
| `quant-tech-history-review.timer` | 周一 04:20，随机延迟最多 10 分钟 | 使用内置缓存搜索索引研究科技史资料；最多 6 次查询，未配置实时来源网页抓取 | `stocks-quant-tech-history-review` |
| `quant-market-temperature.timer` | 启动后 15 分钟，之后每次结束至少 24 小时 | 获取 OFR 官方公开 CSV，一次最多 1 个请求；不是网页爬虫 | `stocks-quant-ofr-market-temperature` |
| `quant-blog-compose.timer` | 每天 19:15 | 从人工审核的本地资料包生成文章草稿，不抓取机构网页 | `stocks-quant-blog-compose` |
| `quant-blog-daily.timer` | 每天 20:30 | 校验本地草稿和人工批准后离线发布 | `stocks-quant-blog-daily-publish` |

另检查到旧财报候选审阅 timer 已在项目文档标记退役，当天也没有出现在活动 timer 列表；它没有作为活动任务导入。分钟行情通知、策略数据更新等非网页新闻监控任务也不在本清单范围。

## SQLite 与接管结果

11 项任务统一为 `scheduler_engine=news-claw`、`enabled=true`。旧 8 个 timer 已 disabled/inactive；Go engine 常驻且开机启动。tasks.task_type 分为 5 项 crawl、5 项 codex、1 项 publish；6 张表不变。

| 旧任务 | Go 计划（北京时间） | 随机延迟 | 迁移前最后结果 |
| --- | --- | --- | --- |
| 市场新闻 RSS | 每小时第 5 分钟 | 0–4 分钟 | 成功 |
| 市场新闻 Codex 分析 | 每 3 小时第 10 分钟 | 0–2 分钟 | 失败 |
| Optimus 供应链复核 | 周一 09:20 | 0–20 分钟 | 失败 |
| 公司脉冲复核 | 周一、周四 10:10 | 0–20 分钟 | 成功 |
| 科技史复核 | 周一 04:20 | 0–10 分钟 | 失败 |
| OFR 市场温度 | 每次结束后至少 24 小时 | 无 | 成功 |
| Codex 长文草稿 | 每天 19:15 | 无 | 程序成功，业务结果需看日志 |
| 长文发布检查 | 每天 20:30 | 无 | 程序成功，业务结果需看日志 |

原 systemd 表达式存放在配置的 legacy_schedule。每个 service 最后一次结果导入 task_runs，注明 engine=systemd，并保存 unit、时间和退出状态；没有导入全部历史运行。OFR 首次计划保持上次结束时间加 24 小时。

旧 service 通过命令适配器执行，保留实际安装的账号、Codex 凭据环境、文件沙箱、原输入输出与发布批准流程。主机实际 service 的账号与仓库模板有差异，因此以安装的 unit 为准。Go 负责时间调度、运行记录、超时、互斥与恢复；systemd 目前仍负责 engine 托管和旧任务执行隔离。

旧 RSS 改为每分钟最多 1 请求，与新 Scrapy 任务通过 web-fetch 串行、共享 Google 来源间隔与熔断状态，保留原网站 news_timeline.json 输出。新主题 RSS 与旧市场 RSS 的文档索引尚未统一，来源请求协调已经接入。

业务脚本的既有失败会继续作为失败显示，不把调度迁移视为修复。使用与恢复规则见 [engine.md](engine.md)，网站数据和长文链路见 [website-workflow.md](website-workflow.md)。

stocks-quant 的采集规则一并保留在任务配置：单进程串行、最多 6 请求/分钟、请求至少间隔 10 秒、优先缓存、同源进程锁；遇到 429、验证码、拒绝或黑名单时停止该来源，不自动重试，不使用代理或切换 IP。BaoStock 因黑名单状态保持暂停，没有将其列为可恢复采集来源。

重建本地任务索引：

```bash
python3 scripts/init_db.py
```
