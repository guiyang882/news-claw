# 沪深300日线采集（2026-10-14：尚未启用）

用户选择免费 AKShare，并明确要求先确认接口限流，避免新加坡固定出口被封。
目标仅为沪深300成分股的日线开高低收、成交量，附带成交额；不复权，不触发任何策略。

## 当前结果

- 独立 `.venv-akshare` 已安装 AKShare 1.19.1，不修改新闻采集、研究、网站环境。
- `csi300-akshare-daily` 已登记 news-claw，但 `enabled=false`，无下一次运行时间。
- 2026-10-14 检查了 AKShare 官方股票文档和对应 SDK；没有找到东方财富
  `push2his.eastmoney.com/api/qt/stock/kline/get` 或腾讯对应行情端点的提供方公开额度承诺。
  第三方“实测频率”不作为额度依据。没有向这些行情端点发出任何请求。
- 当前名单为已有 2026-08-31 历史快照，共300只，附原文件SHA-256；
  `verified_current=false`，不能声称是10月现行成分或用于历史时点回测。
- 米筐试用环境保留但未配置凭据、未调度；原有交易策略暂停标记保持有效。

## 启动前置条件

须取得提供方对端点访问和限流的明确说明，并记录 `access_review` 的
`status=approved`、`endpoint`、`evidence_reference`、`reviewed_by`、`valid_until`、
`minimum_interval_seconds` 与 `max_requests_per_day`。没有这些信息，
即使传入 `--execute` 也在导入 AKShare 或联网之前失败退出。
还须核验沪深300名单当前有效期，更新有来源依据的 `valid_through` 和
`verified_current`。不能只修改布尔值绕过核验。

本地预设每60秒最多一次、单次/每日最多300次，仅是更保守的技术上限，
不是提供方配额或“不封IP”的保证。获准后先显式执行 `--max-requests 1`，
核查原响应、价格和单位，再决定正式启用，不能直接运行300只批次。

## 运行方式

```bash
cd /mnt/quant/news-claw
python3 -m venv .venv-akshare
.venv-akshare/bin/python -m pip install -r requirements-akshare.txt
.venv-akshare/bin/python -m collectors.akshare_daily
.venv-akshare/bin/python -m unittest discover -s tests -p test_akshare_daily.py -v
```

默认命令只预览。手动执行还需 `--execute --max-requests N`。
正式任务预设北京时间周二到周六06:30，目标仅到前一自然日；节假日、
停牌或上游延迟导致空结果时停止待检查，不填零、不推断已完整采集。
启动日拟为2026-10-01，仅采最近数据，未经确认不扩展多年全量历史。

## 数据与防护

数据位于 `/mnt/quant-state/akshare-daily`，不写回策略报告或网站。
`bars/<symbol>.csv` 为规范日线，`raw/` 保存源响应及SHA-256，
`progress.json` 保存每股实际返回末日和缓存哈希，`batches.jsonl` 保存每批结果。
成交量按东方财富文档从手转换为股；成交额为元；不复权价格不拼接复权价格。
重复日期、非数值、负成交量、错误OHLC边界都会拒绝写入。

采集全程使用文件锁；跨进程持久化每日预算和上次请求时间。
限定单一HTTPS端点；无代理、并发、重试或自动切换数据源；不跟随重定向。
非200、空数据、网络/解析/校验异常均持久熔断，下一次执行不联网。
缓存完整性校验通过才增量采集；覆盖率与任务退出状态分别记录。
恢复熔断须先诊断并记录依据，不自动清除。

## 核查来源

- AKShare 股票文档：https://akshare.akfamily.xyz/data/stock/stock.html
- AKShare 官方项目：https://github.com/akfamily/akshare
- 已安装版本源码：`akshare/stock_feature/stock_hist_em.py` 的 `stock_zh_a_hist`
- 本地名单来源与哈希：`config/universes/csi300-akshare.json`

只完成离线验证；未将其标为“线上取数成功”或“每日自动更新已恢复”。
