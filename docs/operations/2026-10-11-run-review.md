# 2026-10-11 运行排查

统计窗口：北京时间 2026-10-10 21:47 至 2026-10-11 21:47。以 SQLite task_runs 的实际启动时间统计，共 39 轮：32 成功、7 失败，失败涉及 5 项任务。

## 失败任务与原因

| 任务 ID | 失败 / 运行次数 | 原因 | 处理 |
| --- | --- | --- | --- |
| us-china-export-controls-daily | 1 / 1 | Google News robots.txt 拒绝 /rss/search | 改用 Federal Register API，按贸易与管制关键词筛选公告 |
| ai-products-attention-daily | 2 / 2 | 同上 | 改用 Google AI 博客、OpenAI RSS 与 Hacker News RSS |
| robotics-physical-ai-space-daily | 2 / 2 | 同上 | 改用 NASA 与 NVIDIA RSS，筛选关键词并区分航天、机器人主题 |
| daily-blog-agy-codex | 1 / 1 | 初稿复核发现无依据内容；事实纠错稿英文 3237 词，低于 3400 词下限 | 增加一次有上限的篇幅修订，反馈实测字数并保留完整复核流程 |
| stocks-quant-market-news-analysis | 1 / 8 | overall.evidence_event_ids 出现重复或未知事件 ID | 模型输出 schema 限定本轮合法 ID；合并完全相同的引用，未知与跨公司引用继续拒绝 |

市场新闻刷新 24 轮及 OFR 刷新 1 轮均成功。市场分析失败后，随后 7 轮成功。科技史、公司脉冲和 Optimus 复核未在窗口内到期，不计为失败。两个原博客任务已停用，保留历史。

此次未发现调度器漏调度或重叠领取的问题。主要问题在来源选择和模型输出；执行层此前仅保存 exit status 1，也增加了排查成本。Go 现在将执行程序 result.json 中的 error/errors 摘要写入 task_runs.error。

## 修复与验证

- 保留 robots 检查、HTTP 401/403/429 熔断及请求预算。不同域名和任务之间共享至少 10 秒请求间隔，缓存命中不占网络额度。
- 增加 Federal Register 公告列表解析、RSS 正文提取、关键词过滤和来源级主题归属。公告摘要与 RSS 仍受既有证据边界约束，不能当作已独立核验的全文。
- 每日博客 max_length_repairs=1，在初稿与事实纠错稿之间共享一次修订预算。反馈中英文实测字数、下限、目标和上限；修订不允许改变来源 ID、标签或事实核验记录，后续必须独立复核。再次不达标仍停止。
- 模型调用上限从 7 次调整为 8 次，篇幅修订超时为 900 秒；参数同步到实际任务及模板。供应方错误、拒绝或限流不进入内容修订重试。
- 网站分析修复位于 stocks-quant 的 `web/news_analysis.py` 与 `web/prompts/overall.txt`，对应提交 `6a3098b`。模型的有效引用列表由本轮输入生成，发布端原有引用与公司归属校验保留。

离线验证：25 项博客测试、10 项真实 Go→Scrapy→本地 HTTP 集成测试、14 项网站分析/模型配置/权限测试全部通过，Go `-race` 测试通过。新用例覆盖短纠错稿、共享修订预算、元数据不变、robots 拒绝、跨域名限流、公告过滤和模型引用限定。

配置已通过 make init 同步至 SQLite，news-claw.service 已重启并保持 active。网站分析使用 CLI 服务入口，下一轮启动时直接读取已更新代码。

## 实际采集试跑

| 任务 | 运行 ID | 结果 | 扫描条目 | 新增文档 |
| --- | --- | --- | --- | --- |
| 政策追踪 | e5931de3df8cb966387f82260cd1de9a | succeeded | 50 | 0 |
| AI 产品 | c852a1befd6389f63b3f042cf34ac60a | succeeded | 1337 | 5 |
| 机器人与航天 | 3442cb4d7d6e572db4293634829edc7e | succeeded | 28 | 5 |

三轮在北京时间 21:57–21:59 完成，合计 13 次网络请求，含 robots 与重定向，全部遵守共享间隔。政策追踪回看窗口内没有新的匹配公告，0 新增是有效结果。历史失败记录未改为成功，试跑使用独立运行 ID。

博客本日的失败尝试记录保留，下一轮仍为 2026-10-12 北京时间 07:30 加最多 7 分钟随机延迟。此次博客与市场分析使用离线模型替身验证，尚未通过新一轮真实模型调用确认输出质量；下一轮继续执行相同的事实、引用和篇幅校验。

## 仍需跟踪

Rocket Lab 投资者站的权限检查返回 HTTP 403，已停止该来源并持久化熔断，没有纳入启用的来源列表。当前 NASA/NVIDIA 来源不保证覆盖 Tesla、SpaceX、Rocket Lab 的全部公告。Hacker News 首页 RSS 只覆盖部分讨论，不能据此量化海外总体关注度；Muse 产品消歧仍需完善。

来源核验报告保存在忽略提交的 data/runs/source-verification/，每轮完整日志与资料保存在 data/runs/&lt;run_id&gt;/，任务配置和业务结果快照可从 SQLite 查询。
