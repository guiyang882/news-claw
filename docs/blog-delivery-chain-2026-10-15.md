# 日更博客任务交接与交付检查

> 历史运行记录：当前已改为周五、周日两期发布，排期以 [每周发布运行说明](blog-weekly-schedule.md) 为准。

## 已部署的任务链（北京时间）

| 时间 | news-claw task | 作用 |
| --- | --- | --- |
| 06:55 | daily-blog-primary-evidence | 沿用官方 RSS 缓存发现与限额正文采集 |
| 07:20、09:20 | daily-blog-readiness | 零网络、零模型的本地材料检查 |
| 07:30、09:30，随机延迟 0–420 秒 | daily-blog-agy-codex | 首次写作及条件补启动 |
| 10:55 | daily-blog-delivery-audit | 核对当天是否实际发布、双语源文件哈希是否合法 |

07:30 和 09:30 的写作入口都会重新检查实时条件，不依赖较早检查任务留下的成功标记。
新增两个检查任务通过现有 news-claw Go engine 管理，不建立另一个 cron 或 Codex 自动化。

## 准入条件

`workflow.readiness` 可配置以下要求，生产已启用：

- 官方正文任务在当天北京时间内运行结束，任务状态和业务结果均成功；关闭、未运行、
  运行中、失败及昨天的成功记录都不算。
- 来源先经过现有 `collect_packet` 的本地路径及内容哈希校验；至少 2 个不同 URL 的
  完整网页正文，每篇至少 1,000 字符，来源发布日期位于最近 14 天内。
- 至少 1 个完整正文 URL 未被近 7 天已发布文章使用。标题摘要、短文本、未知日期和
  未来日期不能填充正文配额。已有研究快照仍可作为补充，不替代这项最低正文要求。

这只是启动门槛，不代表来源事实已被独立核实，也不保证材料一定支持有价值的长文。
候选选题、引用定位、反论证、篇幅、独立事实复核、humanizer 和终审继续执行。
来源日期、封面、公式排版等既有处理保留。

## 有限恢复与失败分类

材料检查失败时返回 `preflight_blocked`、`needs_attention=true`，保存 `readiness.json`，
包含上游运行 ID、正文数量、未使用来源数及原因；不会调用模型，也不占用每日模型尝试。
因此若上游任务只是延迟，09:30 可以重新检查并首次启动。此补启动不增加网络采集次数。

一旦当天已进入模型阶段，原每日尝试记录立即生效。第二个时间槽遇到写作、审核、
模型服务或证据选题失败，会返回 `previous_attempt_failed`，引用原运行，不再调用模型。
不会自动重置服务熔断、删失败标记、提高 10 次/日的常规模型额度或放宽审核。
已发布时直接跳过，不会覆盖当天文章或发布第二篇。

需要恢复已进入模型的失败时，沿用现有人工 `manual_recovery` / `manual_replan` 流程：
检查原证据、稿件与审核哈希；只复用支持的检查点；累计祖先调用次数；
证据重选须有变化。临时人工配置仍只能作用于明确的人工队列运行。

10:55 检查读取实际发布 manifest 并验证两种语言源文件哈希。
只有 day marker 或任务退出成功不足以判定已发布。缺文时返回
`daily_publication_missing`、原尝试与材料检查结果；索引损坏则返回 `blog_check_failed`。
这些状态保存在 task_runs 的业务结果中，任务失败可见；不额外发邮件或调用模型。
长任务因互斥锁排队超出检查时刻也会明确显示尚未交付，管理员应查看运行状态。

## 操作与验证

```bash
# 只读核查，不调用模型或网络
web_python=/mnt/quant/strategies/stocks-quant/web/.venv/bin/python
"$web_python" -m workflows.blog_delivery --task daily-blog-readiness --check
"$web_python" -m workflows.blog_delivery --task daily-blog-delivery-audit --check

# 需要留下 news-claw 正式运行记录时，仅入队本地检查任务
bin/news-claw enqueue --task daily-blog-readiness
bin/news-claw enqueue --task daily-blog-delivery-audit
```

81 项博客专项测试通过，包括北京时间跨日、短摘要/过期来源拒绝、不同 URL 去重、
近期已用来源、上游运行中/关闭/业务失败、材料阻塞不消耗模型尝试、虚假发布标记拒绝。
部署前已备份数据库并比对非目标任务的配置；股票下载继续 disabled、next_run_at 为空。
源码经 rsync 同步，配置写入 SQLite 后由常驻 engine 自动重读。

2026-10-15 通过 engine 实际运行验证：材料检查运行
`3116d5a68505ccdeef7baefe97f6a58b` 成功返回 `already_published`；交付检查运行
`b30d372b9af0392a15f5a1ceb70b89a6` 成功返回 `publication_verified`。
另行只读核查缓存：6 个满足要求的完整正文 URL，其中 4 个近期未使用，
当日上游任务状态及业务结果均成功。两项检查均未调用模型或网络。
下一轮完整定时链从 2026-10-16 06:55 开始；这次验证不代表未来选题必然通过审核。
