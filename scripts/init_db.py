#!/usr/bin/env python3
"""Create or upgrade the local SQLite database using numbered SQL migrations."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "db" / "news.sqlite3"
MIGRATIONS_DIR = ROOT / "sql" / "migrations"
TASKS_DIR = ROOT / "config" / "tasks"
TOPICS_DIR = ROOT / "config" / "topics"


def load_configs(directory: Path) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]


def sync_configs(connection: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    topics = load_configs(TOPICS_DIR)
    tasks = load_configs(TASKS_DIR)
    known_topic_ids = {topic["id"] for topic in topics}

    for topic in topics:
        connection.execute(
            """INSERT INTO topics(id, name, description, enabled, config_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name = excluded.name,
                 description = excluded.description,
                 enabled = excluded.enabled,
                 config_json = excluded.config_json,
                 updated_at = excluded.updated_at""",
            (
                topic["id"],
                topic["name"],
                topic.get("description", ""),
                int(topic.get("enabled", True)),
                json.dumps(topic, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )

    for task in tasks:
        missing_topics = set(task.get("topic_ids", [])) - known_topic_ids
        if missing_topics:
            raise ValueError(
                f"Task {task['id']!r} references unknown topic(s): "
                + ", ".join(sorted(missing_topics))
            )
        collector = task.get("collector", {})
        connection.execute(
            """INSERT INTO tasks(id, name, description, task_type, scheduler_engine, enabled,
                                 schedule, timezone, config_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name = excluded.name,
                 description = excluded.description,
                 task_type = excluded.task_type,
                 scheduler_engine = excluded.scheduler_engine,
                 enabled = excluded.enabled,
                 schedule = excluded.schedule,
                 timezone = excluded.timezone,
                 config_json = excluded.config_json,
                 updated_at = excluded.updated_at""",
            (
                task["id"],
                task["name"],
                task.get("description", ""),
                collector.get("type", "custom"),
                task.get("scheduler_engine", "news-claw"),
                int(task.get("enabled", True)),
                task.get("schedule"),
                task.get("timezone", "UTC"),
                json.dumps(task, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
    # Keep historical rows and run records, but stop scheduling definitions
    # whose config files have been removed.
    for table, records in (("topics", topics), ("tasks", tasks)):
        configured_ids = [record["id"] for record in records]
        if configured_ids:
            placeholders = ",".join("?" for _ in configured_ids)
            connection.execute(
                f"UPDATE {table} SET enabled = 0, updated_at = ? "
                f"WHERE id NOT IN ({placeholders}) AND enabled != 0",
                [now, *configured_ids],
            )
        else:
            connection.execute(
                f"UPDATE {table} SET enabled = 0, updated_at = ? WHERE enabled != 0",
                (now,),
            )


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    migration_files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   version INTEGER PRIMARY KEY,
                   name TEXT NOT NULL,
                   applied_at TEXT NOT NULL
               )"""
        )
        applied = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }

        for migration in migration_files:
            version = int(migration.name.split("_", 1)[0])
            if version in applied:
                continue
            connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (
                    version,
                    migration.name,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )

        sync_configs(connection)

    print(f"SQLite database ready: {DB_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
