# SQLite 数据库

运行 `python3 scripts/init_db.py` 创建或同步 `news.sqlite3`。按当前仓库约定，该数据库快照提交到 Git；journal/WAL、锁、备份和其他数据库不提交。schema 升级放在 `sql/migrations/`。运行中的 SQLite 仍是本机状态，Git 快照不作为多个实例共享的队列。

当前保留 6 张表：

- `tasks`：任务 ID、类型、定义、调度引擎和下次计划；任务关联主题放在 `config_json.topic_ids`。
- `task_runs`：每次任务运行一行，通过 `task_id` 关联 `tasks.id`。
- `topics`：长期跟踪的主题定义。
- `documents`：网页文档；来源信息保存在 `source_json`，主题归属保存在 `topic_links_json`。
- `artifacts`：时间线、推理、关系和摘要等主题产物及版本。
- `schema_migrations`：已应用的数据库迁移版本。

当前 11 项任务统一由 news-claw 调度，包含采集、Codex 整理与网站发布。task_runs.metadata_json 保存本轮配置和结果，博客 result.business_status 区分等待审批和已发布。详见 [网站工作流](../../docs/website-workflow.md)。
