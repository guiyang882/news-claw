# 沪深300日线采集

2026-10-15按用户明确要求启用，接入news-claw。详见[启用记录](AKSHARE_ENABLE_2026-10-15.md)。
官方网页行情额度仍未确认；当前为用户要求下的低频运行，不是官方配额承诺。

## 调度

任务 `csi300-akshare-daily` 北京时间周二到周六06:30执行，核验中证官方名单后，
下载截至名单日期的沪深300成分股不复权日线OHLCV，附成交额。
起始2026-10-01，后续按股票实际已存末日增量；不触发交易策略。

行情每60秒一次，单次/每日最多300次，单进程串行，无自动重试或备用来源。
名单每北京时间自然日最多一次下载，优先复用核验过的同日缓存。
节假日使用官方快照日期，不标记尚无来源数据的日期为完成。

## 环境与检查

```bash
cd /mnt/quant/news-claw
.venv-akshare/bin/python -m collectors.akshare_daily
.venv-akshare/bin/python -m unittest discover -s tests -p test_akshare_daily.py -v
.venv-akshare/bin/python -m unittest discover -s tests -p test_csi300_membership.py -v
bin/news-claw tasks
bin/news-claw runs --limit 20
```

默认命令不联网。正式任务使用 `--execute --max-requests 300 --refresh-membership`。
人工执行前应确认没有任务正在运行，不重复enqueue。

## 状态与故障

`/mnt/quant-state/akshare-daily/bars` 保存日线CSV，volume_shares为股，amount_cny为元。
`raw` 保存行情原响应，`membership` 保存名单及每日下载凭证，
`progress.json` 保存每股实际返回末日及哈希，`batches.jsonl` 保存完成批次和覆盖率。

行情 `circuit.json` 或 `membership/circuit.json` 打开后，后续执行停止联网。
HTTP拒绝、限流、空/异常响应、网络故障均须核查，不自动清除熔断，也不更换IP、代理或账号。
单股停牌/源延迟可能使当轮不能完成；不能把任务配置成功当作全市场数据完整。
策略暂停标记 `/etc/quant-strategies.paused` 继续有效。

历史核查：[2026-10-15启用前核查](AKSHARE_REVIEW_2026-10-15.md)。

## 当前状态（2026-10-15）

定时任务已启用，首轮在第二只股票遇到ConnectionError，当前行情源处于持久熔断。
已有1只股票、5根日线；尚未完成沪深300全量采集。
后续定时运行在解除熔断前只做本地状态检查，不请求上游。
