ALTER TABLE tasks
    ADD COLUMN scheduler_engine TEXT NOT NULL DEFAULT 'news-claw';

CREATE INDEX IF NOT EXISTS idx_tasks_scheduler_engine_enabled
    ON tasks(scheduler_engine, enabled);
