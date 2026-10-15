# AKShare 沪深300日线启用前核查 — 2026-10-15

## 结论

官方成分名单核验完成；网页行情接口额度及自动采集许可仍未确认。
`csi300-akshare-daily` 保持 `enabled=false`，未执行行情请求。
用户要求“两项确认没问题后再启用”，因此本次不启用调度，不恢复任何策略。

## 中证官方名单

- 来源：https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/000300cons.xls
- 抓取时间：2026-10-15T02:01:10.602409+00:00；HTTP 200；仅一次请求，无重试或重定向。
- Last-Modified：Wed, 14 Oct 2026 14:35:18 GMT；表内日期：2026-10-14。
- 指数代码全部为000300；300条、300个唯一六位股票代码，无缺失值。
- 上海189只、深圳111只；代码前缀与交易所一致。
- 原始文件：/mnt/quant-state/akshare-daily/membership/2026-10-14/000300cons.xls，67072字节。
- SHA-256：`af5f512eda5822c98fed43b8331c2feb3bed73cf770aa221271890d5e28855bf`。
- 规范名单：`config/universes/csi300-2026-10-14.csv`；接入清单：`config/universes/csi300-akshare.json`。
- 相比原2026-08-31快照，新增0只：无；移除0只：无。
- 仅核实当前发布文件及其日期；没有推断未来调整、历史成员或指数权重。
  下一目标日超过文件日期时仍需更新核验，不能延长有效期来绕过检查。

## 限流证据与未完成事项

1. AKShare股票文档：https://akshare.akfamily.xyz/data/stock/stock.html
   `stock_zh_a_hist` 的单次返回范围描述不是请求频率/每日配额；SDK不是上游额度承诺。
2. 东方财富服务协议：https://about.eastmoney.com/home/protocol
   页面更新日期2025-07-18。六、2提及行情复制与提供的许可限制；
   页面没有给出本任务精确端点的自动采集授权、请求频率或每日额度。
3. 东方财富证券EMT官方FAQ Q27：
   https://emt.eastmoneysec.com/api/help/md_input_2EMTAPI__FAQ.html
   说明EMT特定查询方法的频率；这是带账户权限的另一套接口，
   不适用于 `https://push2his.eastmoney.com/api/qt/stock/kline/get`。

当前没有找到精确网页行情端点的提供方公开额度说明，不能据此声称接口无限制。
本地60秒间隔、每日300次只是自设保护，不构成上游认可或不封禁保证。
没有通过逐渐加压、反复试探、代理、换IP或其他数据源绕过限制。

启动仍需提供方对该端点允许自动获取日线及其频率/每日额度的明确依据，
再更新access_review、重新核验当日成分，并先做单股票样本质量检查。
上述条件满足前，禁止启用全量自动下载；策略保持暂停。
