-- Keep scheduling state separate from config_json, which init_db.py refreshes.
ALTER TABLE tasks ADD COLUMN next_run_at TEXT;
ALTER TABLE tasks ADD COLUMN schedule_fingerprint TEXT;
ALTER TABLE task_runs ADD COLUMN run_after TEXT;

CREATE UNIQUE INDEX idx_task_runs_scheduled_slot
    ON task_runs(task_id, scheduled_for) WHERE scheduled_for IS NOT NULL;
CREATE INDEX idx_task_runs_queue ON task_runs(status, run_after);
