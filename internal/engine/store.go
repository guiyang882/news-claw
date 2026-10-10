package engine

import (
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"github.com/robfig/cron/v3"
)

const Owner = "news-claw"

type Execution struct {
	Command        []string          `json:"command"`
	WorkingDir     string            `json:"working_dir"`
	Env            map[string]string `json:"env,omitempty"`
	TimeoutSeconds int               `json:"timeout_seconds"`
	LockGroup      string            `json:"lock_group,omitempty"`
	User           string            `json:"user,omitempty"`
}

type Config struct {
	ScheduleFormat string    `json:"schedule_format"`
	Execution      Execution `json:"execution"`
	Options        struct {
		Jitter       int  `json:"start_jitter_seconds"`
		InitialDelay int  `json:"initial_delay_seconds"`
		DoNotStart   bool `json:"do_not_start_from_news_claw"`
	} `json:"options"`
}

type Task struct {
	ID, Name, Schedule, Timezone, Engine string
	Enabled                              bool
	RawConfig                            string
	Next, Fingerprint                    sql.NullString
	Config                               Config
}

type RunMeta struct {
	Engine     string          `json:"engine"`
	Trigger    string          `json:"trigger"`
	LockGroup  string          `json:"lock_group"`
	Execution  Execution       `json:"execution"`
	PID        int             `json:"pid,omitempty"`
	TaskConfig json.RawMessage `json:"task_config"`
}

type Run struct {
	ID, TaskID, Status, CreatedAt string
	ScheduledFor, RunAfter        sql.NullString
	Meta                          RunMeta
}

type Store struct{ DB *sql.DB }

func stamp(t time.Time) string { return t.UTC().Format("2006-01-02T15:04:05.000000000Z") }

func parseStamp(s string) (time.Time, error) { return time.Parse(time.RFC3339Nano, s) }

func Open(path string, readOnly bool) (*Store, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	if _, err = os.Stat(absolute); err != nil {
		return nil, fmt.Errorf("database missing; run scripts/init_db.py: %w", err)
	}
	mode := "rw"
	if readOnly {
		mode = "ro"
	}
	dsn := (&url.URL{Scheme: "file", Path: absolute}).String() + "?mode=" + mode + "&_foreign_keys=on&_busy_timeout=10000&_txlock=immediate"
	db, err := sql.Open("sqlite3", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	if err = db.Ping(); err != nil {
		db.Close()
		return nil, err
	}
	var version int
	if err = db.QueryRow("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").Scan(&version); err != nil || version < 4 {
		db.Close()
		return nil, fmt.Errorf("scheduler migration missing; run scripts/init_db.py (version %d): %v", version, err)
	}
	return &Store{DB: db}, nil
}

func (s *Store) Tasks() ([]Task, error) {
	rows, err := s.DB.Query(`SELECT id, name, COALESCE(schedule,''), timezone, scheduler_engine,
        enabled, config_json, next_run_at, schedule_fingerprint FROM tasks ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var tasks []Task
	for rows.Next() {
		var t Task
		if err := rows.Scan(&t.ID, &t.Name, &t.Schedule, &t.Timezone, &t.Engine, &t.Enabled, &t.RawConfig, &t.Next, &t.Fingerprint); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(t.RawConfig), &t.Config); err != nil {
			return nil, fmt.Errorf("task %s: %w", t.ID, err)
		}
		tasks = append(tasks, t)
	}
	return tasks, rows.Err()
}

func (t Task) Managed() bool {
	return t.Enabled && t.Engine == Owner && !t.Config.Options.DoNotStart
}

func (t Task) Calendar() (cron.Schedule, time.Duration, error) {
	if t.Config.ScheduleFormat == "completion_interval" {
		interval, err := time.ParseDuration(t.Schedule)
		if err != nil || interval <= 0 {
			return nil, 0, fmt.Errorf("invalid completion interval %q", t.Schedule)
		}
		return nil, interval, nil
	}
	if t.Config.ScheduleFormat != "" && t.Config.ScheduleFormat != "cron" {
		return nil, 0, fmt.Errorf("convert schedule_format %q before transfer", t.Config.ScheduleFormat)
	}
	loc, err := time.LoadLocation(t.Timezone)
	if err != nil {
		return nil, 0, err
	}
	// Parse five fields only: a config cannot override the separately stored timezone.
	parser := cron.NewParser(cron.Minute | cron.Hour | cron.Dom | cron.Month | cron.Dow)
	schedule, err := parser.Parse(t.Schedule)
	if err != nil {
		return nil, 0, err
	}
	schedule.(*cron.SpecSchedule).Location = loc
	return schedule, 0, nil
}

func (t Task) Validate() error {
	if len(t.Config.Execution.Command) == 0 || t.Config.Execution.Command[0] == "" {
		return errors.New("execution.command must contain an executable and arguments")
	}
	if t.Config.Execution.TimeoutSeconds <= 0 {
		return errors.New("execution.timeout_seconds must be positive")
	}
	if t.Config.Options.Jitter < 0 || t.Config.Options.InitialDelay < 0 {
		return errors.New("delay and jitter must be nonnegative")
	}
	_, _, err := t.Calendar()
	return err
}

func (t Task) fingerprint() string {
	value := t.Schedule + "\n" + t.Timezone + "\n" + t.RawConfig
	h := sha256.Sum256([]byte(value))
	return hex.EncodeToString(h[:])
}

func newID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}

func metadata(t Task, trigger string) string {
	b, _ := json.Marshal(RunMeta{Engine: Owner, Trigger: trigger, LockGroup: t.Config.Execution.LockGroup, Execution: t.Config.Execution, TaskConfig: json.RawMessage(t.RawConfig)})
	return string(b)
}

// Plan persists at most one pending scheduled run per task. An overdue slot
// represents all missed slots; the next calendar slot is strictly after now.
func (s *Store) Plan(now time.Time) error {
	tasks, err := s.Tasks()
	if err != nil {
		return err
	}
	for _, t := range tasks {
		if !t.Managed() {
			if _, err = s.DB.Exec(`UPDATE task_runs SET status='cancelled', finished_at=?, error='task disabled or externally owned'
                WHERE task_id=? AND status='queued' AND json_extract(metadata_json,'$.engine')=?`, stamp(now), t.ID, Owner); err != nil {
				return err
			}
			if _, err = s.DB.Exec("UPDATE tasks SET next_run_at=NULL, schedule_fingerprint=NULL WHERE id=? AND (next_run_at IS NOT NULL OR schedule_fingerprint IS NOT NULL)", t.ID); err != nil {
				return err
			}
			continue
		}
		if err = t.Validate(); err != nil {
			return fmt.Errorf("task %s: %w", t.ID, err)
		}
		if err = s.planTask(t, now); err != nil {
			return fmt.Errorf("plan %s: %w", t.ID, err)
		}
	}
	return nil
}

func (s *Store) planTask(t Task, now time.Time) error {
	schedule, interval, _ := t.Calendar()
	tx, err := s.DB.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	// Re-read inside the write transaction in case another planner changed it.
	var raw, engine string
	var enabled bool
	if err = tx.QueryRow("SELECT config_json,scheduler_engine,enabled,next_run_at,schedule_fingerprint FROM tasks WHERE id=?", t.ID).
		Scan(&raw, &engine, &enabled, &t.Next, &t.Fingerprint); err != nil {
		return err
	}
	if raw != t.RawConfig || !enabled || engine != Owner {
		return tx.Commit()
	}
	fingerprint := t.fingerprint()
	if !t.Fingerprint.Valid || t.Fingerprint.String != fingerprint {
		if _, err = tx.Exec(`UPDATE task_runs SET status='cancelled',finished_at=?,error='task configuration changed'
            WHERE task_id=? AND status='queued' AND json_extract(metadata_json,'$.trigger')='schedule'`, stamp(now), t.ID); err != nil {
			return err
		}
		next := now.Add(time.Duration(t.Config.Options.InitialDelay) * time.Second)
		if interval == 0 {
			next = schedule.Next(now)
			if next.IsZero() {
				return errors.New("schedule has no future occurrence")
			}
		}
		t.Next = sql.NullString{String: stamp(next), Valid: true}
	}
	var pending int
	if err = tx.QueryRow("SELECT COUNT(*) FROM task_runs WHERE task_id=? AND status IN ('queued','running')", t.ID).Scan(&pending); err != nil {
		return err
	}
	if interval > 0 && !t.Next.Valid && pending == 0 {
		var finished sql.NullString
		if err = tx.QueryRow("SELECT MAX(finished_at) FROM task_runs WHERE task_id=?", t.ID).Scan(&finished); err != nil {
			return err
		}
		if finished.Valid {
			last, e := parseStamp(finished.String)
			if e != nil {
				return e
			}
			t.Next = sql.NullString{String: stamp(last.Add(interval)), Valid: true}
		}
	}
	if t.Next.Valid && pending == 0 {
		next, e := parseStamp(t.Next.String)
		if e != nil {
			return e
		}
		if !next.After(now) {
			jitter := int64(0)
			if t.Config.Options.Jitter > 0 {
				n, e := rand.Int(rand.Reader, big.NewInt(int64(t.Config.Options.Jitter)+1))
				if e != nil {
					return e
				}
				jitter = n.Int64()
			}
			if _, err = tx.Exec(`INSERT OR IGNORE INTO task_runs
                (id,task_id,status,scheduled_for,run_after,metadata_json,created_at)
                VALUES (?,?,'queued',?,?,?,?)`, newID(), t.ID, stamp(next), stamp(now.Add(time.Duration(jitter)*time.Second)), metadata(t, "schedule"), stamp(now)); err != nil {
				return err
			}
			t.Next = sql.NullString{}
			if interval == 0 {
				t.Next = sql.NullString{String: stamp(schedule.Next(now)), Valid: true}
			}
		}
	}
	if _, err = tx.Exec("UPDATE tasks SET next_run_at=?, schedule_fingerprint=? WHERE id=? AND (next_run_at IS NOT ? OR schedule_fingerprint IS NOT ?)", t.Next, fingerprint, t.ID, t.Next, fingerprint); err != nil {
		return err
	}
	return tx.Commit()
}

func (s *Store) Enqueue(id string, now time.Time) (string, error) {
	tasks, err := s.Tasks()
	if err != nil {
		return "", err
	}
	for _, t := range tasks {
		if t.ID != id {
			continue
		}
		if !t.Managed() {
			return "", errors.New("task is disabled, externally owned, or blocked from migration")
		}
		if err = t.Validate(); err != nil {
			return "", err
		}
		tx, err := s.DB.Begin()
		if err != nil {
			return "", err
		}
		defer tx.Rollback()
		var currentRaw, currentOwner string
		var enabled bool
		if err = tx.QueryRow("SELECT config_json,scheduler_engine,enabled FROM tasks WHERE id=?", id).Scan(&currentRaw, &currentOwner, &enabled); err != nil {
			return "", err
		}
		if !enabled || currentOwner != Owner || currentRaw != t.RawConfig {
			return "", errors.New("task changed while enqueuing; reload and try again")
		}
		// One pending run per task, including concurrent manual requests.
		var count int
		if err = tx.QueryRow("SELECT COUNT(*) FROM task_runs WHERE task_id=? AND status IN ('queued','running')", id).Scan(&count); err != nil {
			return "", err
		}
		if count != 0 {
			return "", errors.New("task already has a queued or running instance")
		}
		runID := newID()
		if _, err = tx.Exec(`INSERT INTO task_runs(id,task_id,status,run_after,metadata_json,created_at)
            VALUES (?,?,'queued',?,?,?)`, runID, id, stamp(now), metadata(t, "manual"), stamp(now)); err != nil {
			return "", err
		}
		return runID, tx.Commit()
	}
	return "", fmt.Errorf("unknown task %q", id)
}

func (s *Store) Claim(now time.Time) (*Run, error) {
	tx, err := s.DB.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	var r Run
	var meta string
	err = tx.QueryRow(`SELECT r.id,r.task_id,r.status,r.created_at,r.scheduled_for,r.run_after,r.metadata_json
        FROM task_runs r JOIN tasks t ON t.id=r.task_id
        WHERE r.status='queued' AND r.run_after<=? AND t.enabled=1 AND t.scheduler_engine=?
          AND COALESCE(json_extract(t.config_json,'$.options.do_not_start_from_news_claw'),0)=0
          AND json_extract(r.metadata_json,'$.engine')=?
          AND NOT EXISTS (SELECT 1 FROM task_runs active WHERE active.status='running'
            AND (active.task_id=r.task_id OR
              (COALESCE(json_extract(r.metadata_json,'$.lock_group'),'')!=''
               AND json_extract(active.metadata_json,'$.lock_group')=json_extract(r.metadata_json,'$.lock_group'))))
        ORDER BY r.run_after,r.created_at,r.id LIMIT 1`, stamp(now), Owner, Owner).
		Scan(&r.ID, &r.TaskID, &r.Status, &r.CreatedAt, &r.ScheduledFor, &r.RunAfter, &meta)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if err = json.Unmarshal([]byte(meta), &r.Meta); err != nil {
		return nil, err
	}
	if _, err = tx.Exec("UPDATE task_runs SET status='running',started_at=? WHERE id=? AND status='queued'", stamp(now), r.ID); err != nil {
		return nil, err
	}
	r.Status = "running"
	return &r, tx.Commit()
}

func (s *Store) Recover(now time.Time) error {
	_, err := s.DB.Exec(`UPDATE task_runs SET status='failed',finished_at=?,
        error='engine interrupted; outcome unknown, inspect outputs before manual retry'
        WHERE status='running' AND json_extract(metadata_json,'$.engine')=?`, stamp(now), Owner)
	return err
}

func (s *Store) Finish(r *Run, status string, runErr error, result map[string]any, now time.Time) error {
	meta, _ := json.Marshal(r.Meta)
	var values map[string]any
	_ = json.Unmarshal(meta, &values)
	if result != nil {
		values["result"] = result
	}
	meta, _ = json.Marshal(values)
	var message any
	if runErr != nil {
		message = runErr.Error()
	}
	_, err := s.DB.Exec(`UPDATE task_runs SET status=?,finished_at=?,error=?,metadata_json=?,items_seen=?,items_new=? WHERE id=? AND status='running'`,
		status, stamp(now), message, string(meta), counter(result, "items_seen"), counter(result, "items_new"), r.ID)
	return err
}

func counter(result map[string]any, key string) int64 {
	if v, ok := result[key].(float64); ok && v >= 0 {
		return int64(v)
	}
	return 0
}

func (s *Store) Runs(limit int) ([]map[string]any, error) {
	rows, err := s.DB.Query(`SELECT id,task_id,status,scheduled_for,run_after,started_at,finished_at,items_seen,items_new,error,log_path
        FROM task_runs ORDER BY created_at DESC,id DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	columns, _ := rows.Columns()
	result := []map[string]any{}
	for rows.Next() {
		values := make([]any, len(columns))
		ptrs := make([]any, len(columns))
		for i := range values {
			ptrs[i] = &values[i]
		}
		if err = rows.Scan(ptrs...); err != nil {
			return nil, err
		}
		row := map[string]any{}
		for i, column := range columns {
			row[column] = values[i]
		}
		result = append(result, row)
	}
	return result, rows.Err()
}

func resolve(root, path string) string {
	if filepath.IsAbs(path) {
		return path
	}
	return filepath.Join(root, path)
}

func cleanEnv(base []string, overrides map[string]string) []string {
	values := map[string]string{}
	for _, pair := range base {
		key, value, ok := strings.Cut(pair, "=")
		if ok {
			values[key] = value
		}
	}
	for key, value := range overrides {
		values[key] = value
	}
	result := make([]string, 0, len(values))
	for key, value := range values {
		result = append(result, key+"="+value)
	}
	return result
}
