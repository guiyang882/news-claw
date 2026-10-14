# 2026-10-14 策略暂停与数据采集核查

## 用户要求与实际范围

用户要求检查数据下载能否持续，并暂停效果不佳的存量交易策略。
策略调度实际由 systemd 管理，不在 news-claw 的任务配置中。
本次仅暂停自动策略运行和通知，保留代码、回测、行情缓存、模拟账户绑定、
持仓、目标文件、通知队列和历史记录；未提交任何调仓或平仓请求。

已停用并停止三个 timer：`quant-notify.timer`、`quant-xueqiu-executor.timer`、
`quant-strategy-daily.timer`；通知发送器 `quant-notify-dispatch.service` 也已停用停止。
四个对应 service 均无运行进程。每日更新 service 的旧 failed 状态保留用于审计。

暂停的六个监控实例：低波趋势5股、低波趋势10股、低波60R12、低波20R12、
低波60R08、稳健精选50。每日更新原覆盖三个策略：
`csi300_steady_midvol_50_v1`、`csi300_steady_midvol_100_v1`、
`csi300_mainboard_steady20_v1`，该更新链路整体暂停。

## 持久化暂停

生产 `/etc/quant-notify/config.json` 已设置 `dispatch_enabled=false` 和
`xueqiu_execution.mode=disabled`。原始配置保存在本机受限的
`playground/quant-task-audit-20261014/notify-config.before.json`，不加入 Git。
六个策略定义保留原样：配置加载器要求定义为 running，因此实际暂停以调度层为准。

`/etc/quant-strategies.paused` 为持久化暂停标记。
四个 service 的 `90-user-pause.conf` 均安装自
`/mnt/quant/strategies/stocks-quant/deployment/quant-strategy-pause.conf`，使用反向 ConditionPathExists；
标记存在时 systemd 不执行服务，即使误启 timer 也不能恢复策略。
验证配置加载成功、所有 timer disabled/inactive、启动条件不成立，
news-claw 与两个网站服务继续 active。没有调用联网 probe、tick、调仓或通知测试。

恢复须用户明确要求；先解决数据源权限/配额、审核缓存与积压通知及目标有效期，
再按需调整运行配置、移除暂停标记、启用所需 timer。不要直接恢复旧通知队列发送。

## 数据下载核查结果

news-claw 中 11 个 crawl 任务保持启用并有下一次调度：
五家公司官方来源、AI 产品、机器人/航天、中美管制、博客一手资料、
三家公司新闻线索、OFR 市场压力数据。除新增博客资料任务仅有一次成功记录外，
其余十项最近三次均成功。核查了 result.json 内部采集结果，未仅依据进程退出码。
公司任务的数据库 items_seen/items_new 顶层为零，但 collection 子对象有实际统计，
因此数据库顶层的零不代表未抓到内容。

核查时最新批次：Google 新增2条、NVIDIA新增3条、AI产品新增74条、
机器人/航天新增132条、中美管制新增27条；Amazon、Coinbase、TSMC成功读取来源，
去重后无新增。博客资料新增2条并命中1个缓存。
OFR 于北京时间10月14日14:11下载成功，快照最新观测日为10月9日；
采集时间与来源数据日期分开记录，不将来源发布滞后标为当天行情。
已有请求间隔、缓存、进程锁和拒绝熔断保持不变，未增加采集请求或频率。

行情日线链路存在实际阻塞：北京时间10月9日06:39，Tushare Pro的
`index_weight`（399300.SZ，2026年9月成分权重）返回40203，打开全链路熔断。
此前同批 daily、官方CSI指数、stock_basic 请求成功，但该批整体失败，不能当作完整更新。
此前最后完整批次目标为9月30日。10月14日06:39任务仍因熔断退出，没有重新联网。
原BaoStock来源保留10001011黑名单暂停。没有清除熔断或用其他出口绕过限制。

后续需用户提供当前Tushare接口权限/配额或合法替代来源信息，才能决定恢复方式。
若保留日线下载，应将采集与策略回放/发布分离，不能为下载而重新启用暂停的策略。
本次未伪称A股行情下载已恢复，也未新建未经确认的数据下载任务。
当前研究任务可继续调度的结论来自近期运行证据，不是对未来来源可用性的保证。
