# Radar 上下游依赖

第四个 Tab 由“公司对照”改为“上下游依赖”，兼容原 `tab=cross-company` 链接。
按投入/支撑 → 当前公司 → 客户/交付组织，每个关系可以查看中英文说明、真实披露日期、来源和核验问题。
供应商、客户、平台、合作方、内部能力、基础设施分别标注；合作不推导采购金额、独家关系或收入份额。

## 数据与证据

`web/data/company_dependencies.json` 是版本化的初始快照，共八家公司、14 条关系。
运行时文件为 `/mnt/quant-state/quant-web/company_dependencies.json`，通过 `web/company_dependencies.py` 校验后由认证 content bridge 提供。
文件缺失/损坏时回退初始快照；日常更新原子替换 JSON，无需重建 Next.js 或重启服务。
每个公司单独保留核对日期，来源保留实际披露日期；未获新证据不修改日期。

资料并非完整供应链。缺失方向显示待补充核验；历史披露明确标注，未推断协议至今仍有效。
Tesla 的两条 AI5 双源制造记录来自站内既有经营资料复核，标记 `published_review` 和原始文字稿缓存缺口，不当作本次新获取的原文。其他 12 条具有对应官方正文摘录。

## news-claw

- `company-dependencies-evidence`：每日北京时间 07:20，从已缓存的官方 feed 发现最多 4 篇关系类正文。只访问核定官方 host/path，robots 生效，复用 HTTP/正文缓存，串行、全局至少 10 秒间隔，总计最多 8 个网络请求（包含 robots 和重定向）。403/429/权限错误/识别出的 200 验证挑战打开持久熔断，不自动重试。
- `company-dependencies-review`：每日北京时间 07:45，读取最多 2 篇哈希校验通过的官方正文，最多两次无工具模型调用：提取、独立复核。只发布有精确摘录、匹配 source/candidate hash、双语与 schema 校验通过的关系。失败保留原快照；每日预留一次机会，失败不自动重跑。暂无支持关系时记录 `no_supported_relationships`，不伪装成内容更新。
- 两个任务均由 news-claw 队列、任务锁和运行审计管理，不增加另一套 systemd timer。默认预览不联网，执行需要显式 `--execute` 及正在运行的引擎任务。
- 初始自动发现使用现有 NASA、Google、NVIDIA、AWS 官方 feed 缓存。八家公司都可作为关系主体，但并不意味着八家每天都有新正文；Coinbase、Tesla、TSMC 等新来源扩展仍须验证端点权限和 robots 后加入白名单。已暂停的 SEC、行情与交易策略不恢复。

2026-10-15 试跑：正文采集任务 `a957cc0620b09c1ddf4cea1b8669264c` 用 4 次请求缓存 2 篇正文；复核任务 `4610d30ce36bcd583d29bd18191ff7a0` 两阶段成功，结果无新增可支持关系，保持初始快照。

## 验证与维护

网站：`web/.venv/bin/python -m unittest discover -s tests -p test_web_company_dependencies.py`。
工作流：`/mnt/quant/strategies/stocks-quant/web/.venv/bin/python -m unittest discover -s tests -p test_dependencies.py`（news-claw 目录）。
浏览器：`web/frontend/scripts/browser-dependencies.py <本机候选地址> <输出目录>`，覆盖八家公司、中英文、手机、无 JS、关系详情、四个真 Tab 与历史导航。
发布按候选目录构建、smoke、保留旧静态文件、原子切换流程执行；使用 rsync 传输，数据库、抓取正文、缓存、运行日志不进入 Git。
