package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/guiyang882/news-claw/internal/engine"
)

func main() {
	if err := run(); err != nil {
		log.Print(err)
		os.Exit(1)
	}
}

func run() error {
	if len(os.Args) < 2 {
		return fmt.Errorf("usage: news-claw <check|tasks|runs|plan|enqueue|serve> [flags]")
	}
	action := os.Args[1]
	flags := flag.NewFlagSet(action, flag.ContinueOnError)
	rootFlag := flags.String("root", ".", "repository root")
	dbFlag := flags.String("db", "data/db/news.sqlite3", "SQLite path relative to root")
	taskID := flags.String("task", "", "task ID to enqueue")
	limit := flags.Int("limit", 20, "number of recent runs")
	workers := flags.Int("workers", 2, "maximum running child processes")
	poll := flags.Duration("poll", 5*time.Second, "configuration and queue polling interval")
	once := flags.Bool("once", false, "plan once and drain ready runs, then exit")
	if err := flags.Parse(os.Args[2:]); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected arguments: %v", flags.Args())
	}
	root, err := filepath.Abs(*rootFlag)
	if err != nil {
		return err
	}
	dbPath := *dbFlag
	if !filepath.IsAbs(dbPath) {
		dbPath = filepath.Join(root, dbPath)
	}
	// Normalize symlinks so two aliases cannot create different singleton locks.
	dbPath, err = filepath.EvalSymlinks(dbPath)
	if err != nil {
		return err
	}
	readOnly := action == "tasks" || action == "runs" || action == "check"
	store, err := engine.Open(dbPath, readOnly)
	if err != nil {
		return err
	}
	defer store.DB.Close()
	output := json.NewEncoder(os.Stdout)
	output.SetIndent("", "  ")
	switch action {
	case "tasks", "check":
		tasks, err := store.Tasks()
		if err != nil {
			return err
		}
		result := []map[string]any{}
		for _, task := range tasks {
			row := map[string]any{"task_id": task.ID, "name": task.Name, "task_type": task.Type, "enabled": task.Enabled, "scheduler_engine": task.Engine,
				"managed": task.Managed(), "schedule": task.Schedule, "timezone": task.Timezone, "next_run_at": task.Next.String}
			if task.Managed() {
				if err := task.Validate(); err != nil {
					return fmt.Errorf("task %s: %w", task.ID, err)
				}
			}
			result = append(result, row)
		}
		return output.Encode(result)
	case "runs":
		if *limit <= 0 {
			return fmt.Errorf("limit must be positive")
		}
		runs, err := store.Runs(*limit)
		if err != nil {
			return err
		}
		return output.Encode(runs)
	case "plan":
		lock, err := engine.LockEngine(dbPath)
		if err != nil {
			return err
		}
		defer lock.Close()
		return store.Plan(time.Now())
	case "enqueue":
		id, err := store.Enqueue(*taskID, time.Now())
		if err != nil {
			return err
		}
		return output.Encode(map[string]string{"run_id": id, "task_id": *taskID, "status": "queued"})
	case "serve":
		ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
		defer cancel()
		runner := engine.Runner{Store: store, Root: root, DBPath: dbPath, Workers: *workers, Poll: *poll}
		return runner.Serve(ctx, *once)
	default:
		return fmt.Errorf("unknown command %q", action)
	}
}
