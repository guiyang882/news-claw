# news-claw

把长期关注的新闻，整理成有来源、可复核的研究文章。

news-claw 用于持续追踪新闻与事件：定时采集线索，积累主题材料，再通过 Gemini 和 Codex 完成选题、写稿与复核，发布到网站。

## 从新闻到文章

```mermaid
flowchart LR
    A[采集与归档] --> B[候选选题与大纲]
    B --> C[Gemini 写稿]
    C --> D[Codex 复核与修订]
    D --> E[网站发布]
```

每日博客由 Codex 生成候选题与大纲，Gemini 撰写中英双语长文，每种语言的目标阅读时间约 20 分钟。经过事实复核、humanizer 修订和最终复核后，文章发布到网站，并出现在博客、Feed 与 Sitemap 中。材料不足或复核未通过时，保存稿件与问题记录，停止该轮发布。

## 当前关注的主题

| 主题 | 关注问题 |
| --- | --- |
| 中美进出口管制 | 政策有哪些变化，涉及哪些行业和公司？ |
| AI 产品与 Agent | 海外如何讨论 Muse、Gemini Agent、GPT，用户反馈如何？ |
| 机器人、物理 AI 与商业航天 | Tesla、Rocket Lab、SpaceX 等公司的技术与产业进展如何？ |

当前接入 Federal Register、Google AI 博客、OpenAI、Hacker News、NASA 与 NVIDIA 的公开 RSS 或 API。产品反馈的代表性与政策影响需要进一步整理；长文写作需要正文或研究材料支撑。采集器支持 RSS、Atom 和网页，可继续添加来源。

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

从 [任务模板](config/templates/README.md) 开始，已有采集、Codex、agy / Gemini、发布和每日博客五类模板：

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
| 网站输入输出与发布接入 | [网站工作流](docs/website-workflow.md) |
| 常驻服务与模型运行环境 | [部署说明](deployment/README.md) |
| 数据结构与主题材料归档 | [SQLite](data/db/README.md) · [主题知识](data/knowledge/README.md) |
