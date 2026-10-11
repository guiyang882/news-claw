//go:build linux

package engine

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strconv"
	"sync"
	"syscall"
	"time"
)

type Runner struct {
	Store        *Store
	Root, DBPath string
	Workers      int
	Poll         time.Duration
	Lock         *os.File
}

// The child inherits this descriptor. After an engine crash a replacement
// cannot recover/claim work while an old child still holds the lock.
func LockEngine(dbPath string) (*os.File, error) {
	f, err := os.OpenFile(dbPath+".lock", os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, fmt.Errorf("engine or previous worker still holds database lock: %w", err)
	}
	return f, nil
}

func (r *Runner) Serve(ctx context.Context, once bool) error {
	if r.Workers < 1 || r.Poll <= 0 {
		return errors.New("workers and poll interval must be positive")
	}
	lock, err := LockEngine(r.DBPath)
	if err != nil {
		return err
	}
	r.Lock = lock
	defer lock.Close()
	tasks, err := r.Store.Tasks()
	if err != nil {
		return err
	}
	for _, t := range tasks {
		if t.Managed() {
			if err = t.Validate(); err != nil {
				return fmt.Errorf("task %s: %w", t.ID, err)
			}
		}
	}
	if err = r.recoverExecutions(ctx); err != nil {
		return err
	}
	if err = r.Store.Recover(time.Now()); err != nil {
		return err
	}
	if err = r.Store.Plan(time.Now()); err != nil {
		return err
	}
	workerCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	var workers sync.WaitGroup
	defer workers.Wait()
	done := make(chan error, r.Workers)
	active := 0
	ticker := time.NewTicker(r.Poll)
	defer ticker.Stop()
	for {
		if ctx.Err() != nil {
			return nil
		}
		for active < r.Workers {
			run, err := r.Store.Claim(time.Now())
			if err != nil {
				cancel()
				return err
			}
			if run == nil {
				break
			}
			active++
			workers.Add(1)
			go func() {
				defer workers.Done()
				done <- r.Execute(workerCtx, run)
			}()
		}
		if once && active == 0 {
			return nil
		}
		select {
		case <-ctx.Done():
			return nil
		case err := <-done:
			active--
			if err != nil {
				cancel()
				return err
			}
		case <-ticker.C:
			if !once {
				if err := r.Store.Plan(time.Now()); err != nil {
					// A malformed hot-reloaded config must stop new launches.
					cancel()
					return err
				}
			}
		}
	}
}

// Adapters can own work outside the process group. Their configured recovery
// command must succeed before interrupted runs release queue/source locks.
func (r *Runner) recoverExecutions(ctx context.Context) error {
	rows, err := r.Store.DB.Query(`SELECT id,task_id,metadata_json FROM task_runs WHERE status='running'
        AND json_extract(metadata_json,'$.engine')=?`, Owner)
	if err != nil {
		return err
	}
	var runs []Run
	for rows.Next() {
		var raw string
		var run Run
		if err = rows.Scan(&run.ID, &run.TaskID, &raw); err != nil {
			rows.Close()
			return err
		}
		if err = json.Unmarshal([]byte(raw), &run.Meta); err != nil {
			rows.Close()
			return err
		}
		if len(run.Meta.Execution.RecoveryCommand) > 0 {
			runs = append(runs, run)
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, run := range runs {
		if err = r.recoverExecution(ctx, run); err != nil {
			return err
		}
	}
	return nil
}

func (r *Runner) recoverExecution(ctx context.Context, run Run) error {
	execution := run.Meta.Execution
	if len(execution.RecoveryCommand) == 0 {
		return nil
	}
	timeout := execution.RecoveryTimeoutSeconds
	if timeout <= 0 {
		timeout = 120
	}
	command := execution.RecoveryCommand[0]
	if command == "" {
		return fmt.Errorf("empty recovery executable for run %s", run.ID)
	}
	if command[0] == '.' {
		command = resolve(r.Root, command)
	}
	stopCtx, cancel := context.WithTimeout(ctx, time.Duration(timeout)*time.Second)
	defer cancel()
	cmd := exec.CommandContext(stopCtx, command, execution.RecoveryCommand[1:]...)
	cmd.Dir = resolve(r.Root, execution.WorkingDir)
	cmd.Env = cleanEnv(os.Environ(), execution.Env)
	cmd.Env = cleanEnv(cmd.Env, map[string]string{"NEWS_CLAW_ROOT": r.Root, "NEWS_CLAW_DB": r.DBPath,
		"NEWS_CLAW_TASK_ID": run.TaskID, "NEWS_CLAW_RUN_ID": run.ID})
	cmd.WaitDelay = time.Second
	output, err := cmd.CombinedOutput()
	log.Printf("run=%s recovery error=%v output=%s", run.ID, err, output)
	if err != nil {
		return fmt.Errorf("recover interrupted run %s: %w (%s)", run.ID, err, output)
	}
	return nil
}

func (r *Runner) Execute(parent context.Context, run *Run) error {
	log.Printf("run=%s task=%s started", run.ID, run.TaskID)
	execution := run.Meta.Execution
	runDir := filepath.Join(r.Root, "data", "runs", run.ID)
	if err := os.MkdirAll(runDir, 0750); err != nil {
		return r.Store.Finish(run, "failed", err, nil, time.Now())
	}
	logPath := filepath.Join(runDir, "worker.log")
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0640)
	if err != nil {
		return r.Store.Finish(run, "failed", err, nil, time.Now())
	}
	defer f.Close()
	if len(run.Meta.TaskConfig) > 0 {
		if err = os.WriteFile(filepath.Join(runDir, "task.json"), run.Meta.TaskConfig, 0600); err != nil {
			return r.Store.Finish(run, "failed", err, nil, time.Now())
		}
	}
	relLog, _ := filepath.Rel(r.Root, logPath)
	if _, err = r.Store.DB.Exec("UPDATE task_runs SET log_path=? WHERE id=?", relLog, run.ID); err != nil {
		return err
	}
	if len(execution.Command) == 0 || execution.TimeoutSeconds <= 0 {
		return r.Store.Finish(run, "failed", errors.New("invalid execution snapshot"), nil, time.Now())
	}
	ctx, cancel := context.WithTimeout(parent, time.Duration(execution.TimeoutSeconds)*time.Second)
	defer cancel()
	command := execution.Command[0]
	if command[0] == '.' {
		command = resolve(r.Root, command)
	}
	cmd := exec.Command(command, execution.Command[1:]...)
	cmd.Dir = resolve(r.Root, execution.WorkingDir)
	cmd.Env = cleanEnv(os.Environ(), execution.Env)
	cmd.Env = cleanEnv(cmd.Env, map[string]string{
		"NEWS_CLAW_ROOT": r.Root, "NEWS_CLAW_DB": r.DBPath,
		"NEWS_CLAW_TASK_ID": run.TaskID, "NEWS_CLAW_RUN_ID": run.ID,
		"NEWS_CLAW_RESULT_PATH":      filepath.Join(runDir, "result.json"),
		"NEWS_CLAW_TASK_CONFIG_PATH": filepath.Join(runDir, "task.json"),
	})
	cmd.Stdout, cmd.Stderr = f, f
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if execution.User != "" {
		account, lookupErr := user.Lookup(execution.User)
		if lookupErr != nil {
			return r.Store.Finish(run, "failed", lookupErr, nil, time.Now())
		}
		uid, uidErr := strconv.ParseUint(account.Uid, 10, 32)
		gid, gidErr := strconv.ParseUint(account.Gid, 10, 32)
		if uidErr != nil || gidErr != nil {
			return r.Store.Finish(run, "failed", errors.New("invalid execution user identity"), nil, time.Now())
		}
		if os.Geteuid() != int(uid) {
			cmd.SysProcAttr.Credential = &syscall.Credential{Uid: uint32(uid), Gid: uint32(gid)}
		}
	}
	if r.Lock != nil {
		cmd.ExtraFiles = []*os.File{r.Lock}
	}
	if parent.Err() != nil {
		return r.Store.Finish(run, "cancelled", parent.Err(), nil, time.Now())
	}
	err = cmd.Start()
	if err == nil {
		run.Meta.PID = cmd.Process.Pid
		meta, _ := json.Marshal(run.Meta)
		if _, dbErr := r.Store.DB.Exec("UPDATE task_runs SET metadata_json=? WHERE id=?", string(meta), run.ID); dbErr != nil {
			_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
			_ = cmd.Wait()
			if recoveryErr := r.recoverExecution(context.Background(), *run); recoveryErr != nil {
				return recoveryErr
			}
			return r.Store.Finish(run, "failed", dbErr, nil, time.Now())
		}
		wait := make(chan error, 1)
		go func() { wait <- cmd.Wait() }()
		select {
		case err = <-wait:
		case <-ctx.Done():
			_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM)
			gracePeriod := 5 * time.Second
			if execution.StopGraceSeconds > 0 {
				gracePeriod = time.Duration(execution.StopGraceSeconds) * time.Second
			}
			grace := time.NewTimer(gracePeriod)
			select {
			case <-wait:
			case <-grace.C:
				_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
				<-wait
			}
			grace.Stop()
			err = ctx.Err()
		}
		// A command may exit while descendants continue; don't leave them running.
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	status := "succeeded"
	if err != nil {
		status = "failed"
		if parent.Err() != nil {
			status = "cancelled"
		}
	}
	var result map[string]any
	if body, readErr := os.ReadFile(filepath.Join(runDir, "result.json")); readErr == nil {
		if parseErr := json.Unmarshal(body, &result); parseErr != nil && err == nil {
			err, status = fmt.Errorf("invalid result.json: %w", parseErr), "failed"
		}
		if ok, present := result["success"].(bool); present && !ok && err == nil {
			err, status = errors.New("task executor reported an unsuccessful run"), "failed"
		}
		if status == "failed" {
			detail, _ := result["error"].(string)
			if detail == "" {
				if messages, ok := result["errors"].([]any); ok {
					for _, message := range messages {
						if text, ok := message.(string); ok && text != "" {
							if detail != "" {
								detail += "; "
							}
							detail += text
							if len(detail) >= 2000 {
								break
							}
						}
					}
				}
			}
			if detail != "" {
				if len(detail) > 2000 {
					detail = detail[:2000]
				}
				err = fmt.Errorf("%v: %s", err, detail)
			}
		}
	}
	// A killed adapter can leave external work alive. Keep the run/source locked
	// until cleanup succeeds; on failure Serve exits and restart retries cleanup.
	cleanup, _ := result["recovery_required"].(bool)
	if cleanup || ctx.Err() != nil || (err != nil && cmd.Process != nil && result == nil) {
		if recoveryErr := r.recoverExecution(context.Background(), *run); recoveryErr != nil {
			return recoveryErr
		}
	}
	log.Printf("run=%s task=%s status=%s error=%v", run.ID, run.TaskID, status, err)
	return r.Store.Finish(run, status, err, result, time.Now())
}
