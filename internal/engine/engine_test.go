package engine

import (
	"context"
	"database/sql"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func testStore(t *testing.T) (*Store, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "test.sqlite3")
	db, err := sql.Open("sqlite3", path)
	if err != nil {
		t.Fatal(err)
	}
	files, _ := filepath.Glob("../../sql/migrations/*.sql")
	for _, file := range files {
		body, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = db.Exec(string(body)); err != nil {
			t.Fatal(file, err)
		}
	}
	_, err = db.Exec("INSERT INTO schema_migrations VALUES (4,'test',?)", stamp(time.Now()))
	if err != nil {
		t.Fatal(err)
	}
	db.Close()
	store, err := Open(path, false)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.DB.Close() })
	return store, path
}

func addTask(t *testing.T, s *Store, id, schedule, format, group string) {
	t.Helper()
	c := Config{ScheduleFormat: format, Execution: Execution{Command: []string{"/bin/true"}, TimeoutSeconds: 10, LockGroup: group}}
	c.Options.Jitter = 300
	c.Options.InitialDelay = 15
	b, _ := json.Marshal(c)
	_, err := s.DB.Exec(`INSERT INTO tasks(id,name,task_type,scheduler_engine,enabled,schedule,timezone,config_json,created_at,updated_at)
        VALUES (?,?,'test',?,1,?,'Asia/Shanghai',?,?,?)`, id, id, Owner, schedule, string(b), stamp(time.Now()), stamp(time.Now()))
	if err != nil {
		t.Fatal(err)
	}
}

func taskByID(t *testing.T, s *Store, id string) Task {
	t.Helper()
	tasks, err := s.Tasks()
	if err != nil {
		t.Fatal(err)
	}
	for _, task := range tasks {
		if task.ID == id {
			return task
		}
	}
	t.Fatal("missing task", id)
	return Task{}
}

func TestCalendarAndDurableCoalescing(t *testing.T) {
	s, path := testStore(t)
	addTask(t, s, "daily", "15 7 * * *", "cron", "google")
	base := time.Date(2026, 10, 10, 0, 0, 0, 0, time.UTC)
	if err := s.Plan(base); err != nil {
		t.Fatal(err)
	}
	task := taskByID(t, s, "daily")
	want := stamp(time.Date(2026, 10, 10, 23, 15, 0, 0, time.UTC))
	if task.Next.String != want {
		t.Fatalf("timezone: got %s want %s", task.Next.String, want)
	}
	later := base.Add(5 * 24 * time.Hour)
	if err := s.Plan(later); err != nil {
		t.Fatal(err)
	}
	var count int
	var scheduled, after string
	s.DB.QueryRow("SELECT COUNT(*),scheduled_for,run_after FROM task_runs").Scan(&count, &scheduled, &after)
	if count != 1 || scheduled != want {
		t.Fatalf("missed slots were not coalesced: %d %s", count, scheduled)
	}
	at, _ := parseStamp(after)
	if at.Before(later) || at.After(later.Add(300*time.Second)) {
		t.Fatal("jitter out of bounds", at)
	}
	restarted, err := Open(path, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.DB.Close()
	if err = restarted.Plan(later.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
	var persisted string
	restarted.DB.QueryRow("SELECT run_after FROM task_runs").Scan(&persisted)
	if persisted != after {
		t.Fatal("jitter changed after restart")
	}
	if _, err = s.DB.Exec("INSERT INTO task_runs(id,task_id,status,scheduled_for,created_at) VALUES ('duplicate','daily','queued',?,?)", scheduled, stamp(later)); err == nil {
		t.Fatal("scheduled slot uniqueness missing")
	}
}

func TestCompletionIntervalStartsAfterFinish(t *testing.T) {
	s, _ := testStore(t)
	addTask(t, s, "interval", "24h", "completion_interval", "")
	now := time.Now().UTC()
	if err := s.Plan(now); err != nil {
		t.Fatal(err)
	}
	if err := s.Plan(now.Add(20 * time.Second)); err != nil {
		t.Fatal(err)
	}
	run, err := s.Claim(now.Add(time.Hour))
	if err != nil || run == nil {
		t.Fatal(run, err)
	}
	finished := now.Add(3 * time.Hour)
	if err := s.Finish(run, "succeeded", nil, nil, finished); err != nil {
		t.Fatal(err)
	}
	if err := s.Plan(finished); err != nil {
		t.Fatal(err)
	}
	if next := taskByID(t, s, "interval").Next.String; next != stamp(finished.Add(24*time.Hour)) {
		t.Fatal("completion interval is not measured from finish", next)
	}
}

func TestImportedCompletionDeadlineIsPreserved(t *testing.T) {
	s, _ := testStore(t)
	addTask(t, s, "ofr", "24h", "completion_interval", "web-fetch")
	now := time.Now().UTC()
	deadline := now.Add(22 * time.Hour)
	s.DB.Exec("UPDATE tasks SET config_json=json_set(config_json,'$.options.first_run_at',?) WHERE id='ofr'", stamp(deadline))
	if err := s.Plan(now); err != nil {
		t.Fatal(err)
	}
	if next := taskByID(t, s, "ofr").Next.String; next != stamp(deadline) {
		t.Fatal("legacy completion deadline lost", next)
	}
}

func TestGenericRecoveryUsesRunSnapshotAndKeepsLockOnFailure(t *testing.T) {
	s, db := testStore(t)
	root := t.TempDir()
	addTask(t, s, "adapter", "* * * * *", "cron", "source")
	if _, err := s.Enqueue("adapter", time.Now()); err != nil {
		t.Fatal(err)
	}
	run, err := s.Claim(time.Now().Add(time.Second))
	if err != nil || run == nil {
		t.Fatal("claim", err)
	}
	run.Meta.Execution.RecoveryCommand = []string{"/bin/false"}
	body, _ := json.Marshal(run.Meta)
	if _, err = s.DB.Exec("UPDATE task_runs SET metadata_json=? WHERE id=?", string(body), run.ID); err != nil {
		t.Fatal(err)
	}
	runner := Runner{Store: s, DBPath: db, Root: root}
	if err = runner.recoverExecutions(context.Background()); err == nil {
		t.Fatal("failed adapter recovery was ignored")
	}
	var status string
	s.DB.QueryRow("SELECT status FROM task_runs WHERE id=?", run.ID).Scan(&status)
	if status != "running" {
		t.Fatal("failed recovery released the run", status)
	}
	// A relative command gets its original environment and working directory.
	script := "#!/bin/sh\n[ \"$NEWS_CLAW_TASK_ID\" = adapter ] && [ \"$RECOVERY_TEST\" = snapshot ] && touch recovered\n"
	if err = os.WriteFile(filepath.Join(root, "recover"), []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	run.Meta.Execution.RecoveryCommand = []string{"./recover"}
	run.Meta.Execution.Env = map[string]string{"RECOVERY_TEST": "snapshot"}
	body, _ = json.Marshal(run.Meta)
	s.DB.Exec("UPDATE task_runs SET metadata_json=? WHERE id=?", string(body), run.ID)
	if err = runner.recoverExecutions(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err = os.Stat(filepath.Join(root, "recovered")); err != nil {
		t.Fatal("recovery hook not executed", err)
	}
	if err = s.Recover(time.Now()); err != nil {
		t.Fatal(err)
	}
	s.DB.QueryRow("SELECT status FROM task_runs WHERE id=?", run.ID).Scan(&status)
	if status != "failed" {
		t.Fatal("interrupted execution was not marked unknown", status)
	}
}

func TestConcurrentClaimUsesSharedSourceGroup(t *testing.T) {
	s, path := testStore(t)
	now := time.Now()
	addTask(t, s, "one", "* * * * *", "cron", "google")
	addTask(t, s, "two", "* * * * *", "cron", "google")
	for _, id := range []string{"one", "two"} {
		if _, err := s.Enqueue(id, now); err != nil {
			t.Fatal(err)
		}
	}
	var wg sync.WaitGroup
	claimed := make(chan *Run, 8)
	errors := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			other, err := Open(path, false)
			if err != nil {
				errors <- err
				return
			}
			defer other.DB.Close()
			run, err := other.Claim(now.Add(time.Second))
			if err != nil {
				errors <- err
			} else if run != nil {
				claimed <- run
			}
		}()
	}
	wg.Wait()
	if len(errors) != 0 || len(claimed) != 1 {
		t.Fatalf("claim race: claims=%d errors=%d", len(claimed), len(errors))
	}
	if err := s.Finish(<-claimed, "succeeded", nil, nil, now.Add(2*time.Second)); err != nil {
		t.Fatal(err)
	}
	if run, err := s.Claim(now.Add(3 * time.Second)); err != nil || run == nil {
		t.Fatal("second source job never released", run, err)
	}
}

func TestOwnershipPauseAndRecovery(t *testing.T) {
	s, _ := testStore(t)
	addTask(t, s, "new", "* * * * *", "cron", "")
	addTask(t, s, "old", "hourly", "systemd_timer", "")
	s.DB.Exec("UPDATE tasks SET scheduler_engine='systemd',enabled=0 WHERE id='old'")
	if _, err := s.Enqueue("old", time.Now()); err == nil {
		t.Fatal("external timer launched")
	}
	if _, err := s.Enqueue("new", time.Now()); err != nil {
		t.Fatal(err)
	}
	s.DB.Exec("UPDATE tasks SET enabled=0 WHERE id='new'")
	if run, err := s.Claim(time.Now().Add(time.Second)); run != nil || err != nil {
		t.Fatal("disabled queue claimed", err)
	}
	if err := s.Plan(time.Now()); err != nil {
		t.Fatal(err)
	}
	var status string
	s.DB.QueryRow("SELECT status FROM task_runs WHERE task_id='new'").Scan(&status)
	if status != "cancelled" {
		t.Fatal("pending pause did not cancel", status)
	}
	s.DB.Exec("UPDATE tasks SET enabled=1 WHERE id='new'")
	s.Enqueue("new", time.Now())
	run, err := s.Claim(time.Now().Add(time.Second))
	if err != nil || run == nil {
		t.Fatal(err)
	}
	s.DB.Exec(`INSERT INTO task_runs(id,task_id,status,metadata_json,created_at) VALUES ('external','old','running','{"engine":"systemd"}',?)`, stamp(time.Now()))
	if err := s.Recover(time.Now()); err != nil {
		t.Fatal(err)
	}
	s.DB.QueryRow("SELECT status FROM task_runs WHERE id=?", run.ID).Scan(&status)
	if status != "failed" {
		t.Fatal("interrupted run not recorded")
	}
	s.DB.QueryRow("SELECT status FROM task_runs WHERE id='external'").Scan(&status)
	if status != "running" {
		t.Fatal("external history was changed")
	}
}

func TestSingletonAndExecutionTimeout(t *testing.T) {
	s, db := testStore(t)
	lock, err := LockEngine(db)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Close()
	if second, err := LockEngine(db); err == nil {
		second.Close()
		t.Fatal("second engine acquired lock")
	}
	addTask(t, s, "timeout", "* * * * *", "cron", "")
	s.Enqueue("timeout", time.Now())
	run, _ := s.Claim(time.Now().Add(time.Second))
	run.Meta.Execution = Execution{Command: []string{"/bin/sh", "-c", "sleep 30 & wait"}, TimeoutSeconds: 1}
	runner := Runner{Store: s, DBPath: db, Root: t.TempDir(), Lock: lock}
	if err := runner.Execute(context.Background(), run); err != nil {
		t.Fatal(err)
	}
	var status, message, logPath string
	s.DB.QueryRow("SELECT status,error,log_path FROM task_runs WHERE id=?", run.ID).Scan(&status, &message, &logPath)
	if status != "failed" || !strings.Contains(message, "deadline") || logPath == "" {
		t.Fatal(status, message, logPath)
	}
}

func TestFailedAdapterCleanupRetainsSourceLock(t *testing.T) {
	s, db := testStore(t)
	addTask(t, s, "adapter", "* * * * *", "cron", "source")
	addTask(t, s, "next", "* * * * *", "cron", "source")
	s.Enqueue("adapter", time.Now())
	run, err := s.Claim(time.Now().Add(time.Second))
	if err != nil || run == nil {
		t.Fatal("claim", err)
	}
	run.Meta.Execution.Command = []string{"/bin/false"}
	run.Meta.Execution.RecoveryCommand = []string{"/bin/false"}
	runner := Runner{Store: s, DBPath: db, Root: t.TempDir()}
	if err = runner.Execute(context.Background(), run); err == nil {
		t.Fatal("failed cleanup was ignored")
	}
	var status string
	s.DB.QueryRow("SELECT status FROM task_runs WHERE id=?", run.ID).Scan(&status)
	if status != "running" {
		t.Fatal("uncleaned external work released", status)
	}
	s.Enqueue("next", time.Now())
	if next, err := s.Claim(time.Now().Add(time.Second)); err != nil || next != nil {
		t.Fatal("source lock lost after adapter failure", next, err)
	}
}

func TestWorkerKeepsSingletonLockAfterParentClosesIt(t *testing.T) {
	_, path := testStore(t)
	lock, err := LockEngine(path)
	if err != nil {
		t.Fatal(err)
	}
	child := exec.Command("/bin/sleep", "0.3")
	child.ExtraFiles = []*os.File{lock}
	if err = child.Start(); err != nil {
		lock.Close()
		t.Fatal(err)
	}
	lock.Close()
	if replacement, err := LockEngine(path); err == nil {
		replacement.Close()
		t.Error("replacement acquired lock while old worker still running")
	}
	if err = child.Wait(); err != nil {
		t.Fatal(err)
	}
	replacement, err := LockEngine(path)
	if err != nil {
		t.Fatal("worker failed to release singleton lock", err)
	}
	replacement.Close()
}

func TestConcurrentManualEnqueueCreatesOneRun(t *testing.T) {
	s, path := testStore(t)
	addTask(t, s, "manual", "* * * * *", "cron", "")
	var workers sync.WaitGroup
	success := make(chan string, 6)
	for i := 0; i < 6; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			other, err := Open(path, false)
			if err != nil {
				t.Error(err)
				return
			}
			defer other.DB.Close()
			if id, err := other.Enqueue("manual", time.Now()); err == nil {
				success <- id
			}
		}()
	}
	workers.Wait()
	if len(success) != 1 {
		t.Fatal("manual enqueue race", len(success))
	}
}
