# Google News RSS 恢复

日期：2026-10-11，北京时间。用户明确要求恢复原入口、忽略 Google News RSS 的 robots，并提交、推送变更。

## 配置

- 恢复中美贸易管制、Muse、Gemini Agent、GPT 反馈、商业航天、机器人、物理 AI 的 7 个原 RSS 查询。
- 启用小时级 `stocks-quant-market-news-refresh`，继续给网站更新 Tesla、SpaceX、Rocket Lab 时间线；旧 systemd timer 保持关闭，时间调度由 Go 管理。
- 保留已有 6 个官方与社区补充来源。
- Google 共享最小请求间隔设为 60 秒；跨域间隔至少 10 秒。保留错峰、随机延迟、缓存、互斥、预算和 401/403/429 持久化熔断，没有清除 HTTP 拒绝状态。

## 来源级 robots 开关

```json
{
  "type": "rss",
  "url": "https://news.google.com/rss/search?q=example&hl=en-US&gl=US&ceid=US%3Aen",
  "obey_robots_txt": false
}
```

该设置仅支持 RSS/Atom，默认值为 `true`。Scrapy 全局 robots 检查继续开启；例外只作用于配置的 URL，重定向到其他地址后重新检查 robots。运行结果 `robots_override_urls` 记录实际应用例外的地址。模板显式显示默认值 `true`，后续可直接修改来源 JSON，再执行 `make init` 同步 SQLite。

本次是用户要求的 robots 配置例外，不代表提供方新增了用途许可；原 RSS 的用途说明仍保留在 [核查记录](2026-10-11-google-news-access.md)。没有修改其他来源的 robots 策略。

## 验证

15 项离线集成测试全部通过，使用真实 Go 调度器与 Scrapy，验证默认拒绝、单订阅例外、重定向例外失效、403/429 熔断和跨任务限速。历史失败记录保留原始状态。

4 次线上试跑均成功，由现有 Go 队列按照 `web-fetch` 互斥依次执行：

| 任务 | 运行 ID | 新文档 | 网络请求 | 已应用的 Google RSS 例外 |
| --- | --- | ---: | ---: | ---: |
| 中美管制 | `3c217fe2447ff8ccfa3f78e4d8febc6c` | 40 | 3 | 1 |
| AI 产品 | `128c67f31ab49cd465ca21cace3ae6e3` | 79 | 10 | 3 |
| 机器人与航天 | `5e31c0310d32e66affc2155a1e8711d5` | 123 | 7 | 3 |
| 旧市场网站入口 | `575229a7fa58df1ab3814a9807fbb2ac` | 写入原网站时间线 | 3 | 旧 RSS 阅读器 |

三个新采集任务在北京时间 23:36–23:42 完成，共新增 242 条 Google RSS 文档。旧市场采集器在 23:43:38、23:44:38、23:45:38 分别收到 Rocket Lab、SpaceX、Tesla 订阅；三份缓存 SHA-256 校验通过，网站 `news_timeline.json` 于 23:45:38 更新，保留上限 300 条事件。旧入口仍使用网站原有数据存储，不计入新采集器的文档数。

本轮总计 23 次网络请求，包含补充来源的 robots 与重定向，未取消既有请求间隔。所有定义已同步到 SQLite：12 项任务、10 项启用；完整性与外键检查通过，Go 常驻服务保持运行，原 systemd 定时器未恢复。
