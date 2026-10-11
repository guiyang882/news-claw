# Google News RSS 访问核查

核查日期：2026-10-11，北京时间。此次复用本地 robots、RSS 缓存与运行日志，没有追加 Google News RSS 探测请求。

后续状态：用户随后明确要求忽略 Google RSS 的 robots 并恢复采集，配置现已恢复。本文保留当时核查事实与暂停记录；当前配置和验证结果见 [恢复记录](2026-10-11-google-news-restoration.md)。

## 实际失败原因

三个 Scrapy 新闻任务的五次失败均来自 `Forbidden by robots.txt`。缓存中的 robots 请求返回 HTTP 200；Scrapy 随后在本地拦截 `/rss/search`，没有下载该 RSS 端点。因此，这些记录不能用来判断 Google 对出口 IP 限流或封禁。

Google News 的通用 robots 规则从 `Disallow: /` 开始，允许列表未包含 `/rss`。使用生产采集器相同的 Protego 解析器复核：`/rss`、`/rss/search?q=Tesla` 均不允许，`/home` 与 `/topics/example` 允许。解析器工作正常，调度打散和降低请求频率不会改变路径规则。[Scrapy robots 中间件文档](https://docs.scrapy.org/en/latest/topics/downloader-middleware.html#robotstxtmiddleware)说明了这类请求在下载之前被过滤。

## 为什么旧任务还能成功

stocks-quant 的 `web/news_collector.py` 直接使用 urllib 请求 RSS，没有执行 robots 检查。其最近三份缓存与批次日志证明 RSS 仍能返回内容；不能据此把新采集器的失败说成 HTTP 403/429，也不能把“无需登录”当作网站发布的使用许可。

三份已校验缓存的 `channel/copyright` 均限定为个人、非商业阅读器用途，并排除其他用途。当前项目会整理研究并发布到网站，未找到覆盖这一用途的提供方许可。[Google 服务条款](https://policies.google.com/terms)也要求自动访问遵守机器可读的限制。

证据位置（不提交原始订阅数据）：

- `data/runs/http-cache/news_claw/68/686ae71ee5053bb22e0818485605d2bb4e23ab13/`：robots HTTP 200 与原始规则。
- `/mnt/quant-state/quant-web/news_cache/{rocket_lab,spacex,tesla}.json` 及 `.meta.json`：RSS 使用说明、采集时间与 SHA-256；本次复核通过内容哈希校验。
- `/mnt/quant-state/quant-web/news_collection_batches.jsonl`：旧采集器实际下载成功的批次记录。

## 本次处理

- 在 `task_runs.metadata_json.result.failure_details` 中区分 `robots_denied`、`http_access_denied`、`http_rate_limited`。robots 拦截记录端点、robots 地址和 `blocked_before_download: true`，端点 HTTP 状态为空。
- 暂停 `stocks-quant-market-news-refresh` 的小时级旧 Google RSS 入口，并在 JSON 与 SQLite 中记录原因和恢复条件。此处理也遵守 stocks-quant 的 `AGENTS.md`：明确拒绝不得自动重试、采集必须遵守来源条款。
- 保留原有缓存与历史运行；三个新新闻任务继续使用上一轮已验证的 Federal Register、Google AI 博客、OpenAI、Hacker News、NASA、NVIDIA 来源。

Google News 原入口尚未恢复。当前替代来源不具备 Google News 的聚合搜索覆盖，尤其不能保证 Tesla、SpaceX、Rocket Lab 的完整新闻线索。恢复需要适用于该用途的明确许可，或接入允许研究发布的聚合服务/直接来源；降低频率或修改 User-Agent 都不能解决本次路径和用途限制。

离线验证：真实 Go → Scrapy → 本地 HTTP 的回归用例检查 robots 拦截时没有端点请求，403 与 429 分别分类且不重复请求。数据库同步后，旧入口保持禁用，三个新采集任务仍启用。
