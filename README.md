# news-claw

一个用于定时采集关注的新闻与事件，使用 Codex 或 agy / Gemini 整理为主题知识材料，并发布到 stocks-quant 网站的项目。网站代码位于 `/mnt/quant/strategies/stocks-quant`。

## 目录

```text
config/
  tasks/                 JSON 任务定义：采集、Codex/agy 整理、网站发布
  templates/             采集、模型、发布和每日博客工作流模板，默认关闭
  topics/                主题定义：关注范围、关键词、关注问题
data/
  db/news.sqlite3        本地索引与任务运行状态（由 scripts/init_db.py 创建）
  raw/                   原始网页及抓取元数据，按来源和日期归档
  normalized/            清洗后的正文和结构化记录
  knowledge/topics/      主题级时间线、逻辑线、推理、关系图谱与摘要
  runs/                  每次任务运行的日志和清单
sql/migrations/          按序号执行的 SQLite schema 迁移
scripts/                 本地维护脚本
cmd/news-claw/           Go 调度器命令入口
internal/engine/         持久化计划、队列与子进程执行
collectors/              Scrapy RSS/Atom/网页采集器
workflows/               每日博客等多阶段任务的执行程序
docs/                    监控任务计划与口径
```

## 核心划分

- **Task（任务）** 描述执行什么命令、何时执行、关联哪些主题；任务可以是采集、Codex/agy 分析或发布。稳定 ID 用于关联每轮运行。
- **调度引擎** 记录在 `tasks.scheduler_engine`。12 项任务定义中有 10 项启用，由 Go engine 调度；旧 service 作为执行适配器。每日博客通过直接 CLI 工作流执行，原两项博客任务停用并保留历史。
- **SQLite 结构保持精简**：任务主题关联放在任务配置的 `topic_ids`；来源信息和文档主题关联随文档存为 JSON，减少单独的关联表。
- **Topic（主题）** 描述“长期追踪什么问题”。抓取结果先进入原始归档，再经过去重、正文抽取和主题归属，最后汇总成主题材料。
- **SQLite** 保存任务、主题、任务运行、文档索引和产物版本等可查询元数据；来源和主题关联使用 JSON，网页正文和长文本产物保存在文件中，数据库记录其相对路径与内容哈希。
- **原文不可变**。重新抽取或修订分析时保留原始响应；新产物通过版本和输入指纹追踪其来源。

## 初始化

项目只依赖 Python 标准库即可创建数据库：

```bash
python3 scripts/init_db.py
```

任务和主题定义是 JSON 文件。初始化脚本会将配置同步到 SQLite 的任务和主题表；JSON 文件是定义的来源。移除配置文件会在数据库中停用对应定义，同时保留历史运行记录。时间表达式采用 cron 格式，时区单独声明。新增关注事项时，分别添加任务和主题 JSON，再运行初始化脚本。

采集、Codex 整理、agy / Gemini 整理和发布模板见 [config/templates/README.md](config/templates/README.md)。复制到 config/tasks/ 并配置后即可同步；模板目录本身不参与调度。Codex 的模型、推理强度、速度与权限直接在 JSON 中配置，执行程序读取本轮快照；参数位置见 [网站任务说明](docs/website-workflow.md#codex-参数配置)。

## 文件归档约定

原始网页建议按以下路径保存：

```text
data/raw/webpages/<source_slug>/<YYYY>/<MM>/<DD>/<sha256>.html
data/raw/metadata/<source_slug>/<YYYY>/<MM>/<DD>/<sha256>.json
```

清洗正文以同一文档哈希为主键，保存在 `data/normalized/documents/<sha256>.json`。数据库中的 `raw_path`、`metadata_path` 和 `normalized_path` 均相对于项目根目录。

主题产物按类型和版本组织，例如：

```text
data/knowledge/topics/<topic_slug>/timeline/v001.md
data/knowledge/topics/<topic_slug>/logic/v001.md
data/knowledge/topics/<topic_slug>/inferences/v001.md
data/knowledge/topics/<topic_slug>/relations/v001.json
data/knowledge/topics/<topic_slug>/summaries/v001.md
```

每个主题目录应保留简短的 `README.md` 或产物清单，说明口径、更新时间和引用的文档。关系数据先用 JSON 存储，后续需要图数据库时可从文档与关系边导出。

## 建议的数据流

1. 调度器读取启用的任务定义并创建 `task_runs` 记录。
2. 抓取器保存原始响应和抓取元数据，再登记或更新 `documents`。
3. 清洗与去重步骤生成标准正文，并将候选文档关联到一个或多个主题。
4. 主题整理步骤按时间线、逻辑脉络、推理记录、关系和摘要生成有版本的产物，并登记在 `artifacts`。
5. 每次运行保存输入文档集合、产物版本、统计数据和错误信息，便于增量重跑与回溯。
6. Codex 任务生成网站数据或文章草稿，发布任务校验后写入网站读取的运行目录。每日博客先由 Codex 生成候选题与约 20 分钟阅读的大纲，再由 Gemini 按大纲写稿、Codex 事实复核、humanizer 修订和最终复核；原市场文章人工批准流程保留。

当前已接入 Go 调度器和 Scrapy RSS/Atom/网页采集器，三个新任务以 Google News RSS 开始采集新闻线索。网站数据分析保留原有输入输出。[每日博客](docs/daily-blog.md) 每天北京时间 07:30 加随机延迟运行，先保存候选题和大纲，通过复核后发布中英双语长文并登记知识索引；材料不足或复核不通过时保留记录。运行方式见 [docs/engine.md](docs/engine.md)，网站链路见 [docs/website-workflow.md](docs/website-workflow.md)。

当前任务清单和默认监控口径见 [docs/monitoring-plan.md](docs/monitoring-plan.md)；从 stocks-quant 盘点并登记的旧 systemd 任务见 [docs/stocks-quant-task-inventory.md](docs/stocks-quant-task-inventory.md)。

数据库目前有 6 张表：`tasks`、`task_runs`、`topics`、`documents`、`artifacts` 和 `schema_migrations`。
