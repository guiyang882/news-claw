# SQLite 数据库

运行 `python3 scripts/init_db.py` 创建 `news.sqlite3`。数据库文件是本地运行数据，不提交到版本控制；schema 与后续升级放在 `sql/migrations/`。

当前保留 6 张表：

- `tasks`：任务定义和调度引擎；任务关联主题放在 `config_json.topic_ids`。
- `task_runs`：每次任务运行一行，通过 `task_id` 关联 `tasks.id`。
- `topics`：长期跟踪的主题定义。
- `documents`：网页文档；来源信息保存在 `source_json`，主题归属保存在 `topic_links_json`。
- `artifacts`：时间线、推理、关系和摘要等主题产物及版本。
- `schema_migrations`：已应用的数据库迁移版本。
