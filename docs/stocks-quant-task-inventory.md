# stocks-quant 旧定时任务盘点

盘点时间：2026-10-10（北京时间）。检查了 `/mnt/quant/strategies/stocks-quant/AGENTS.md`、`deployment/*.timer`、配套 service 和运行说明，并查看了主机 `systemctl list-timers --all`。表中的旧 timer 当时均显示已调度；这里没有运行任何抓取脚本、发起外部请求、停用服务或移动旧运行数据。

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

## SQLite 登记与执行边界

上述 8 个任务定义和 3 个补充主题已放入 `config/` 并同步至 `data/db/news.sqlite3`。SQLite `tasks.scheduler_engine` 对这 8 项标为 `systemd`，新建的 3 项监控任务标为 `news-claw`。从旧仓库镜像的任务在本数据库中设置为 `enabled = false`，并在 `config_json` 记录原 unit、原始 systemd 日历表达式、来源/输出路径、当时观察到的 timer 状态和请求上限。false 表示 news-claw 不会启动它们；旧 systemd timer 仍由 stocks-quant 管理，未停用。

`news-claw` 是新任务的目标调度引擎标签；当前仓库还没有执行器，因此这 3 项虽在 SQLite 中启用，仍只是已配置任务，尚未实际调度运行。

目前 `news-claw` 只有任务清单与 SQLite 注册，还没有读取这些定义并实际调度的执行器。特别是旧的小时 Google News RSS timer 仍给 stocks-quant 网站供稿；新建的机器人/物理 AI/太空新闻任务与其有主题重叠。真正切换前应先确定共用来源、缓存和输出的交接方案，再停用旧 timer 或明确保留唯一采集所有者，不能直接同时启用两个采集入口。

stocks-quant 的采集规则一并保留在任务配置：单进程串行、最多 6 请求/分钟、请求至少间隔 10 秒、优先缓存、同源进程锁；遇到 429、验证码、拒绝或黑名单时停止该来源，不自动重试，不使用代理或切换 IP。BaoStock 因黑名单状态保持暂停，没有将其列为可恢复采集来源。

重建本地任务索引：

```bash
python3 scripts/init_db.py
```
