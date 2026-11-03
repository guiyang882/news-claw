# news-claw

把长期关注的新闻，整理成有来源、可复核的公司动态与经营观察。

news-claw 定时采集线索、积累主题材料，生成双语公司简报并复核来源，供网站的市场脉冲、经营验证及上下游依赖使用。

## 从来源到市场脉冲

```mermaid
flowchart LR
    A[采集与归档] --> S[公司简报与主题整理]
    S --> V[来源复核]
    V --> E[市场脉冲与公司观察]
    E --> H[八家公司覆盖及首页巡检]
```

2026-11-03 起，网站专注市场脉冲，文章采集、写作、补稿与发布巡检任务暂停。已发布文章保留，自动化不会继续补发。每小时检查八家公司来源与简报覆盖；没有新披露与采集失败分开记录。详见[市场脉冲运行说明](docs/market-pulse-home.md)。

## 当前关注的主题

| 主题 | 关注问题 |
| --- | --- |
| 中美进出口管制 | 政策有哪些变化，涉及哪些行业和公司？ |
| AI 产品与 Agent | 海外如何讨论 Muse、Gemini Agent、GPT，用户反馈如何？ |
| 机器人、物理 AI 与商业航天 | Tesla、Rocket Lab、SpaceX 等公司的技术与产业进展如何？ |

当前通过 Google News RSS 追踪主题新闻，并接入 Federal Register、Google AI 博客、OpenAI、Hacker News、NASA 与 NVIDIA 的 RSS 或 API。产品反馈的代表性与政策影响需要进一步整理；长文写作需要正文或研究材料支撑。采集器支持 RSS、Atom 和网页，可继续添加来源。

三个主题继续整理材料并校验来源、时间线与推理边界，积累到主题知识库；没有新证据时跳过重复调用。主题整理不触发文章发布。

## 任务如何组织

- **配置**：任务定义放在 `config/tasks/`，长期关注的问题放在 `config/topics/`。时间、来源、执行命令及模型参数都在 JSON 中调整。
- **执行**：Go 调度器管理计划、队列和运行状态；Scrapy 负责采集，配合错峰调度、随机延迟与共享请求限流。Codex、agy / Gemini 和发布脚本使用同一套任务执行协议。
- **积累**：SQLite 保存任务、运行记录和文档索引；原始响应、结构化内容及主题产物保存为文件。输入快照、内容哈希和产物记录帮助追溯文章依据。

## 快速开始

需要 Linux、Go 1.24+、Python 3.11+ 和 C 编译器（SQLite 驱动使用 CGO）。

```bash
git clone https://github.com/guiyang882/news-claw.git
cd news-claw

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
make init
make build

bin/news-claw tasks
```

`make init` 将任务与主题配置同步到 SQLite；`tasks` 只查看任务，不发起采集。内置任务包含现有网站的集成配置，启动调度前需按自己的环境调整启用任务、模型 CLI 路径和发布位置，详见 [部署说明](deployment/README.md)。

## 添加与调整任务

从 [任务模板](config/templates/README.md) 开始，已有采集、Codex、agy / Gemini、发布、每日博客、主题整理和网站维护模板：

```bash
cp config/templates/crawl.json config/tasks/my-topic-daily.json
```

修改任务 ID、来源、关联主题和调度时间，在 [主题配置](config/topics/README.md) 中定义关注范围，然后设置 `enabled: true`。模型、推理强度和速度等参数也在任务 JSON 中配置。模板默认关闭，修改任务后运行 `make init` 同步，常驻调度器会读取更新。

按上述说明配置完成后，可检查配置并在前台启动调度器：

```bash
bin/news-claw check
bin/news-claw serve --workers 2
```

## 进一步阅读

| 内容 | 文档 |
| --- | --- |
| 新增任务、调整时间与模型参数 | [任务模板](config/templates/README.md) · [任务配置](config/tasks/README.md) |
| 队列、限流、恢复与运行命令 | [调度与采集](docs/engine.md) |
| 候选选题、大纲、写稿与复核 | [每日博客工作流](docs/daily-blog.md) |
| Gemini 整理、Codex 校验与知识积累 | [主题整理流程](docs/topic-summaries.md) |
| Google、Amazon、Coinbase 来源与错峰简报 | [公司追踪流程](docs/company-watch.md) |
| 网站输入输出与发布接入 | [网站工作流](docs/website-workflow.md) |
| 常驻服务与模型运行环境 | [部署说明](deployment/README.md) |
| 数据结构与主题材料归档 | [SQLite](data/db/README.md) · [主题知识](data/knowledge/README.md) |
