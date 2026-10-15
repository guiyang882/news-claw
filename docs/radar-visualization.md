# Radar 交互式证据图

## 展示与数据来源

- 经营与验证：四个可选择节点依次展示来源、经营基线、执行节点、待验证项。箭头仅表示核验阅读顺序。
- 七家公司的指标与里程碑直接读取已校验的 `company_pulses`，保留单位、期间、状态、日期、来源和下一步核验问题。
- Tesla 使用 `supply_chain.records`、`redundancy_groups` 和 `coverage_gaps`；不将供应能力当作已确认合作。
- 公司对照：当前公司为中心，分支来自编辑维护的 `COMPANY_COMPARISONS`。点击对象查看其独立简报、日期、来源与研究问题。虚线不代表合作、供应或因果关系。
- 最新简报保留摘要，来源时间线保留时间筛选；不将缺失数据转换为零值、分数或完成百分比。

所有八家公司共用组件；中英文、浅深主题、手机纵向布局与键盘选择均支持。节点点击原地展开，不更改 URL 或滚动锚点；长详情在面板内滚动。无 JavaScript 时保留完整静态节点内容和原始经营资料。

## news-claw 任务约定

更新八个现有任务的 `workflow.presentation_contract`，不增加模型任务、抓取次数或调度频率：

- `company-{google,amazon,coinbase,nvidia,tsmc}-brief`：公司对照使用独立简报；起草、修订及复核全部读取约定。
- `stocks-quant-market-news-analysis`：Rocket Lab、SpaceX、Tesla 的简报仍经现有 schema 和证据校验；网站 `web/prompts/company_output.txt` 明确区分报道、目标、待验证项。
- `stocks-quant-company-pulses-review`：`web/company_pulses_review.py` 保留每项指标与里程碑的来源、日期、单位、口径及可观察的验证信号。
- `stocks-quant-optimus-supplier-review`：`web/optimus_supply_chain_review.py` 保留证据等级和替代关系边界。

模型只生成原 schema 的结构化数据，不生成 SVG、HTML、Mermaid 或额外关系。网页由安全的 React 组件绘图，现有历史快照无需改写即可展示；未来资料通过原发布流程自动更新，无需重新构建前端。

采集限流、持久熔断、审核、共享模型预算及暂停任务保持原配置。此次不调用模型或外部数据源重做已有简报。

## 验证（2026-10-15）

网站相关 Python 测试 28 项、news-claw 公司简报测试 14 项、前端测试 9 项通过。
独立候选目录构建、类型检查及临时状态的完整前端 smoke 通过。
agent-browser 在独立 localhost 预览上逐一切换八家公司全部四个经营节点，验证详情非空、
手机宽度 390px 无横向溢出；另行检查中文桌面图、公司对照选择、深色模式与键盘 Enter 操作。
任务配置同步前在线备份 SQLite，只更新这八个任务的 config_json；调度、下次运行时间、
enabled 状态及其他任务配置逐项比对保持一致。
