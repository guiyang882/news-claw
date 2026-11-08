# stocks-quant 旧定时任务盘点与 2026-11-08 研究工作台适配

盘点与迁移日期：2026-10-10；工作台适配与精简日期：2026-11-08（北京时间）。
网站已全面升级为以 `https://research.growthyoung.com/` 为核心的 8 家标的公司研究工作台（Rocket Lab, SpaceX, Tesla, Google, Amazon, Coinbase, NVIDIA, TSMC）。
可视化展示（View）与声明式数据（Data: `web/frontend/content/`）已彻底分离。

## 2026-11-08 任务精简与分组

为保护出口 IP、避免无谓空跑，调度引擎精简为 **19 个活跃任务**：

1. **8 家公司一手官方新闻/公告采集（7 项）**：
   - `stocks-quant-market-news-refresh` (Rocket Lab, SpaceX, Tesla)
   - `company-google-news`, `company-amazon-news`, `company-coinbase-news`, `company-coinbase-cache-refresh`, `company-nvidia-news`, `company-tsmc-news`
2. **AI 双语研报简报与多空争议初筛（6 项）**：
   - `stocks-quant-market-news-analysis` (Rocket Lab, SpaceX, Tesla)
   - `company-google-brief`, `company-amazon-brief`, `company-coinbase-brief`, `company-nvidia-brief`, `company-tsmc-brief`
3. **经营指标与供应链复核（2 项）**：
   - `stocks-quant-company-pulses-review` (周一、周四 10:10)
   - `stocks-quant-optimus-supplier-review` (周一 09:20)
4. **商业依赖与上下游图谱（2 项）**：
   - `company-dependencies-evidence` (每天 07:20)
   - `company-dependencies-review` (每天 07:45)
5. **宏观压力与全域巡检（2 项）**：
   - `stocks-quant-ofr-market-temperature` (每 24h)
   - `market-pulse-coverage-audit` (每小时)

### 彻底停用/归档的任务（19 项）
- **博客流水线（7 项）**：`daily-blog-*` 与 `stocks-quant-blog-*`（博客自 11-03 起暂停发布）。
- **副主题采集（7 项）**：`ai-products-*`、`us-china-*`、`robotics-*`（纯为博客喂料，无前台承载，已停用以保护出口 IP）。
- **废弃/黑名单（5 项）**：`csi300-akshare-daily`（BaoStock黑名单）、`stocks-quant-tech-history-review` 等。

---

## 历史接管背景 (2026-10-10)

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

最初接管 11 项任务，统一为 `scheduler_engine=news-claw`。当前 15 项定义、13 项启用；旧草稿与发布两项停用并保留历史。新增三个 [Gemini 主题整理与 Codex 校验](topic-summaries.md) 任务，补充每日博客材料。小时级 Google News RSS 于 2026-10-11 核查后暂停，随后按用户要求恢复，详见 [恢复记录](operations/2026-10-11-google-news-restoration.md)。任务类型包含 5 项 crawl、5 项 codex、1 项 publish、4 项 workflow。旧 8 个 timer 已 disabled/inactive；Go engine 常驻且开机启动；6 张表不变。

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

旧 service 通过命令适配器执行，沿用本机账号、Codex 登录环境与原输入输出。用户要求所有模型调用 full 权限后，已更新 CLI 参数，并通过覆盖配置移除 engine 和模型 service 的文件系统限制。每日博客由新工作流直接执行，旧人工批准入口保留。主机实际 service 的账号与仓库模板有差异，因此以安装的 unit 为准。Go 负责时间调度、运行记录、超时、互斥与恢复；systemd 目前仍负责 engine 托管和旧任务的启动。

旧 RSS 已恢复，每分钟最多 1 请求，与新 Scrapy 任务通过 web-fetch 串行、共享 Google 来源间隔与熔断状态，继续更新网站 news_timeline.json。三个新主题采集任务恢复 Google RSS 查询并保留补充来源，其文档索引与旧网站时间线尚未统一。

业务脚本的既有失败会继续作为失败显示，不把调度迁移视为修复。使用与恢复规则见 [engine.md](engine.md)，网站数据和长文链路见 [website-workflow.md](website-workflow.md)。

stocks-quant 的采集规则一并保留在任务配置：单进程串行、最多 6 请求/分钟、请求至少间隔 10 秒、优先缓存、同源进程锁；遇到 429、验证码、拒绝或黑名单时停止该来源，不自动重试，不使用代理或切换 IP。BaoStock 因黑名单状态保持暂停，没有将其列为可恢复采集来源。

重建本地任务索引：

```bash
python3 scripts/init_db.py
```
