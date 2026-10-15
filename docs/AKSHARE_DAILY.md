# 沪深300日线采集

2026-10-15曾按用户要求启用；重复对端断连后，用户明确要求暂停，现已关闭调度。
详见[排查与暂停记录](AKSHARE_CONNECTION_2026-10-15.md)。
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

用户明确要求暂停：`enabled=false`，数据库`next_run_at=NULL`，无运行中或排队批次。
保留2只股票、共10根日线以及原始响应、故障原因、熔断和预算记录。
当前不会自动下载，也不切换到Tushare或其他来源；策略继续暂停。
再次启用需用户新指令，不能仅清除熔断或打开任务开关绕过暂停状态。
