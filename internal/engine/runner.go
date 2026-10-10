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
			return r.Store.Finish(run, "failed", dbErr, nil, time.Now())
		}
		wait := make(chan error, 1)
		go func() { wait <- cmd.Wait() }()
		select {
		case err = <-wait:
		case <-ctx.Done():
			_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM)
			grace := time.NewTimer(5 * time.Second)
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
			err, status = errors.New("collector reported an unsuccessful run"), "failed"
		}
	}
	log.Printf("run=%s task=%s status=%s error=%v", run.ID, run.TaskID, status, err)
	return r.Store.Finish(run, status, err, result, time.Now())
}
