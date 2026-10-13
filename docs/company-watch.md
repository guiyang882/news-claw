# Google、Amazon 与 Coinbase 公司简报

三家公司的来源采集与简报整理分别调度，不扩展原有 Rocket Lab、SpaceX、Tesla 的经营快照和概率分析协议。首页共六家公司，桌面两行三列；新增内容由网站逐次读取，无需为每次更新构建前端。

## 来源与时间

时间均为北京时间，另加最多 180 秒随机延迟。

| 公司 | 来源 | 采集 | 简报 |
| --- | --- | --- | --- |
| Google / Alphabet | `https://blog.google/rss/` | 每四小时 :15 | 每天 10:27 |
| Amazon | `https://aws.amazon.com/blogs/aws/feed/` | 每四小时 :35 | 每天 14:27 |
| Coinbase | `https://www.coinbase.com/blog/feed.xml` | **暂停**；原计划每四小时 :55 | 每天 18:27，材料不足则跳过 |

Google 首页公布 RSS 链接；AWS 官方博客公布订阅入口。Coinbase 投资者关系首页 `https://investor.coinbase.com/home/default.aspx` 中引用其博客 feed。2026-10-13 首次 Coinbase RSS 请求返回 403，已关闭 `company-coinbase-news` 并保留访问拒绝熔断。恢复需要提供方授权和人工来源复核；不得清除熔断后探测、忽略 robots 或切换地址规避拒绝。

当前 Google 来源是产品与公司公告，不等同于 Alphabet 完整财务披露；Amazon 来源覆盖 AWS，不代表零售、广告等全部业务。来源是发行方陈述，整理不等于独立事实验证。

每个采集批次最多 4 次请求（包括 robots），使用原采集器的共享锁、缓存、条件请求、全局至少 10 秒间隔和拒绝熔断。Google 请求间隔至少 60 秒。新采集入口默认只预览；实际执行要求 Go 调度器运行身份、公开免鉴权 RSS 的来源复核记录和明确请求上限。

## 模型预算与发布

- agy 使用 `gemini-3.8-flash-low`（Gemini 3.8 Flash 的低推理档位），每次最多生成一次；Codex 使用 `gpt-6.1-sol` 复核一次。复核不通过保留旧发布，不自动修稿或重试。
- 每家公司每天最多一次尝试；三家合计最多三次，至少间隔一小时。正常计划彼此相隔四小时；现有其他工作流继续共用 `model-cli` 锁和模型提供方熔断。
- 每次最多 8 条近七日来源、16,000 字符输入；每个列表最多两项。三家公司每日预算为 120,000 token，每次预留至少 40,000，CLI 报告实际用量更高时按高值记账。失败和中断也消耗预留；相同证据不重复调用。
- 这是新增任务的保守本地预算，不是账户余额查询或提供方的硬输出限额，不能保证整个 agy 账户永不耗尽。提供方限额拒绝会打开共享熔断。
- 模型只整理本地证据，不联网查资料。复核必须匹配来源和分析的 SHA-256；跨公司、来源变化、无匹配批准记录均不能发布。

采集结果分别写入 `/mnt/quant-state/quant-web/company_news/<company>.json`，批准简报分别写入 `company_briefs/<company>.json`。网站按公司独立校验，缺失显示等待，单家公司出错不影响另外两家。发布采用原子替换，文件归 `quant-web` 所有。

预算记录位于 `data/runs/company-watch-budget/`；运行目录保留输入、模型响应、复核和采集审计。运行数据、私有日志和生产 SQLite 不应随代码提交。

## 运维与验证

修改 JSON 后执行 `python3 scripts/init_db.py`；常驻引擎自动载入更新。手工试跑也只能通过 `bin/news-claw enqueue -task company-google-news` 或 `company-google-brief`，同样受预算和熔断限制。不要一次排入三家公司简报以绕过错峰策略。

2026-10-13 初次验证：Google 发布 20 条、Amazon 发布 17 条来源，各两次请求且遵守 robots；Coinbase 两次请求后在 RSS 的 403 上停止（运行 `1fe4050cdd7b3dd45961f57cfa5bcd46`）。agy 的首次本地参数检查拒绝了 `flash-high` 与 `effort=low` 的冲突组合，零模型轮次、零 token；更正为正式列出的 `flash-low` 后仅释放了这次本地预检预留，原记录保存在运行目录中，实际模型失败仍不得重试。

离线回归：`.venv/bin/python -m unittest discover -s tests -q` 与网站环境执行 `PYTHONPATH=. /mnt/quant/strategies/stocks-quant/web/.venv/bin/python -m unittest discover -s tests_blog -q`。网站的 `tests/test_web_company_watch.py` 验证独立来源、证据哈希、失败隔离和简报时效。

实际 Gemini 试跑 `d1242ddf3a97d96e4ad71d437f88ce19` 生成一次，记录 15,428 token。本地数字字段校验修正后，复用了已存草稿进行唯一一次 Codex 复核；复核指出产品预购范围和 AI 分类等证据外延问题，因此未发布简报、未重复生成。原始来源照常展示，后续新证据按既定计划处理。
