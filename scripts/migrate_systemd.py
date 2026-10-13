#!/usr/bin/env python3
"""Preview or apply the handoff of the eight inventoried timers to the Go engine."""

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/news.sqlite3"
SHARED_CIRCUIT = "/mnt/quant-state/quant-web/news_circuit.json"
JOBS = {
    "stocks-quant-market-news-refresh": ("quant-news-refresh", "5 * * * *", 240, 480, "web-fetch"),
    "stocks-quant-market-news-analysis": ("quant-news-analysis", "10 */3 * * *", 120, 2760, ""),
    "stocks-quant-optimus-supplier-review": ("quant-optimus-supply-review", "20 9 * * 1", 1200, 2160, "web-fetch"),
    "stocks-quant-company-pulses-review": ("quant-company-pulses-review", "10 10 * * 1,4", 1200, 2460, "web-fetch"),
    "stocks-quant-tech-history-review": ("quant-tech-history-review", "20 4 * * 1", 600, 2160, "web-fetch"),
    "stocks-quant-ofr-market-temperature": ("quant-market-temperature", "24h", 0, 120, "web-fetch"),
    "stocks-quant-blog-compose": ("quant-blog-compose", "15 19 * * *", 0, 2760, ""),
    "stocks-quant-blog-daily-publish": ("quant-blog-daily", "30 20 * * *", 0, 600, ""),
}
BUSY = {"active", "activating", "deactivating", "reloading"}


def command(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=30).stdout


def state(unit, properties):
    return dict(line.split("=", 1) for line in command("systemctl", "show", unit, "--property=" + properties).splitlines() if "=" in line)


def stamp(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")


def parse_service_time(value, zone):
    if not value:
        return None
    return datetime.strptime(value.rsplit(" ", 1)[0], "%a %Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(zone))


def prepare_config(task, job, observed, zone):
    unit, schedule, jitter, timeout, group = job
    if "legacy_schedule" not in task:
        task["legacy_schedule"] = {"schedule": task["schedule"], "format": task.get("schedule_format"), "timer": unit + ".timer"}
    task.update(scheduler_engine="news-claw", enabled=True, schedule=schedule,
                schedule_format="completion_interval" if schedule == "24h" else "cron")
    task["name"] = task["name"].removeprefix("历史任务：")
    task["execution"] = {"command": [".venv/bin/python", "-m", "collectors.legacy_service", "--unit", unit + ".service"],
                         "working_dir": ".", "timeout_seconds": timeout, "stop_grace_seconds": 115,
                         "lock_group": group, "adapter": "legacy_service", "systemd_unit": unit + ".service",
                         "recovery_command": ["systemctl", "stop", unit + ".service"], "recovery_timeout_seconds": 110}
    task["task_type"] = "publish" if unit == "quant-blog-daily" else (
        "crawl" if unit in {"quant-news-refresh", "quant-market-temperature"} else "codex")
    if unit == "quant-blog-compose":
        task.setdefault("workflow", {}).update({
            "website_repo": "/mnt/quant/strategies/stocks-quant",
            "stage": "draft",
            "inputs": ["/mnt/quant-state/quant-web/blog/source-packets/YYYY-MM-DD.json"],
            "outputs": ["/mnt/quant-state/quant-web/blog/inbox/YYYY-MM-DD.json"],
            "input_requirement": "existing web.blog_compose.validate_packet must pass; empty input skips",
            "next_task_id": "stocks-quant-blog-daily-publish",
        })
    elif unit == "quant-blog-daily":
        task.setdefault("workflow", {}).update({
            "website_repo": "/mnt/quant/strategies/stocks-quant",
            "stage": "publish",
            "inputs": ["/mnt/quant-state/quant-web/blog/inbox/YYYY-MM-DD.json"],
            "outputs": ["/mnt/quant-state/quant-web/blog/articles"],
            "input_requirement": "existing draft validation and hash-bound editor approval must pass",
            "after_task_id": "stocks-quant-blog-compose",
        })
    elif unit == "quant-news-analysis":
        task.setdefault("workflow", {}).update({
            "website_repo": "/mnt/quant/strategies/stocks-quant",
            "stage": "analyze_and_update_dataset",
            "inputs": ["/mnt/quant-state/quant-web/news_timeline.json"],
            "outputs": ["/mnt/quant-state/quant-web/news_analysis.json"],
            "input_requirement": "existing news-analysis schema and source fingerprint validation must pass",
            "after_task_id": "stocks-quant-market-news-refresh",
        })
    task["options"].pop("do_not_start_from_news_claw", None)
    task["options"].update(migration_state="go_scheduled_legacy_service", start_jitter_seconds=jitter)
    task["collector"].update(execution_owner="news-claw_via_legacy_service", external_timer_active=False,
                             migration_observed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if schedule == "24h":
        finished = parse_service_time(observed.get("ExecMainExitTimestamp", ""), zone)
        task["options"]["first_run_at"] = stamp(finished + timedelta(hours=24)) if finished else stamp(datetime.now(timezone.utc) + timedelta(minutes=15))
    if unit == "quant-news-refresh":
        task["collector"]["request_policy"].update(max_requests_per_minute=1, min_interval_seconds=60,
            shared_circuit_paths=[SHARED_CIRCUIT])
    return task


def import_history(observed, zone):
    with sqlite3.connect(DB) as db:
        for task_id, (unit, *_) in JOBS.items():
            info = observed[unit]
            finished = parse_service_time(info.get("ExecMainExitTimestamp", ""), zone)
            if not finished:
                continue
            started = parse_service_time(info.get("ExecMainStartTimestamp", ""), zone)
            result = info.get("Result", "unknown")
            run_id = "legacy-" + hashlib.sha256((unit + stamp(finished)).encode()).hexdigest()[:24]
            meta = {"engine": "systemd", "imported": True, "systemd_unit": unit + ".service",
                    "service_result": result, "exec_main_status": info.get("ExecMainStatus"),
                    "journal_unit": unit + ".service"}
            db.execute("""INSERT OR IGNORE INTO task_runs
                (id,task_id,status,started_at,finished_at,error,metadata_json,created_at)
                VALUES (?,?,?,?,?,?,?,?)""", (run_id, task_id, "succeeded" if result == "success" else "failed",
                stamp(started) if started else None, stamp(finished), None if result == "success" else "previous systemd result: " + result,
                json.dumps(meta), stamp(finished)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="disable old timers and start the Go scheduler")
    args = parser.parse_args()
    zone = command("timedatectl", "show", "--property=Timezone", "--value").strip()
    observed, timers, configurations = {}, {}, {}
    for task_id, job in JOBS.items():
        unit = job[0]
        observed[unit] = state(unit + ".service", "ActiveState,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp,User,PrivateNetwork")
        timers[unit] = state(unit + ".timer", "ActiveState,UnitFileState")
        configurations[task_id] = json.loads((ROOT / "config/tasks" / (task_id + ".json")).read_text())
        if observed[unit].get("ActiveState") in BUSY:
            raise RuntimeError(f"wait for the existing service before migration: {unit}")
    if state("news-claw.service", "ActiveState").get("ActiveState") in BUSY:
        raise RuntimeError("news-claw is already running; migration is already applied or requires an explicit maintenance stop")
    print(json.dumps({"tasks": len(JOBS), "old_timers": timers, "previous_service_results": observed}, indent=2))
    if not args.apply:
        return
    if not (ROOT / "bin/news-claw").is_file():
        raise RuntimeError("build bin/news-claw before migration")
    backup = ROOT / "data/runs" / ("handoff-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(parents=True)
    original_files = list((ROOT / "config/tasks").glob("*.json"))
    for path in original_files:
        shutil.copy2(path, backup / path.name)
    with sqlite3.connect(DB) as src, sqlite3.connect(backup / "news.sqlite3") as dst:
        src.backup(dst)
    targets = {
        Path("/etc/systemd/system/news-claw.service"): ROOT / "deployment/news-claw.service",
        Path("/etc/systemd/system/quant-news-refresh.service.d/news-claw.conf"): ROOT / "deployment/quant-news-refresh.conf",
    }
    old_units = {str(target): target.read_bytes() if target.exists() else None for target in targets}
    (backup / "states.json").write_text(json.dumps({"timers": timers, "services": observed}, indent=2))
    try:
        command("systemctl", "disable", "--now", *[unit + ".timer" for unit in timers])
        for unit in timers:
            if state(unit + ".service", "ActiveState").get("ActiveState") in BUSY:
                raise RuntimeError(f"service started during handoff; finish it before retry: {unit}")
        for target, template in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template, target)
        command("systemctl", "daemon-reload")
        for task_id, job in JOBS.items():
            task = prepare_config(configurations[task_id], job, observed[job[0]], zone)
            (ROOT / "config/tasks" / (task_id + ".json")).write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n")
        for path in original_files:
            if path.stem in JOBS:
                continue
            task = json.loads(path.read_text())
            task["task_type"] = "crawl"
            task["workflow"] = {
                "website_repo": "/mnt/quant/strategies/stocks-quant",
                "stage": "news_discovery",
                "outputs": ["data/raw", "data/normalized", "documents"],
                "publication_status": "requires_topic_analysis_and_website_adapter",
            }
            task["collector"]["request_policy"]["shared_circuit_paths"] = [SHARED_CIRCUIT]
            path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n")
        command(sys.executable, str(ROOT / "scripts/init_db.py"))
        import_history(observed, zone)
        command(str(ROOT / "bin/news-claw"), "check", "--root", str(ROOT))
        command(str(ROOT / "bin/news-claw"), "plan", "--root", str(ROOT))
        command("systemctl", "enable", "--now", "news-claw.service")
        time.sleep(2)
        if command("systemctl", "is-active", "news-claw.service").strip() != "active":
            raise RuntimeError("engine failed to start")
        with sqlite3.connect(DB) as db:
            managed = db.execute("SELECT count(*) FROM tasks WHERE enabled=1 AND scheduler_engine='news-claw' AND next_run_at IS NOT NULL").fetchone()[0]
        if managed != 11:
            raise RuntimeError(f"unexpected planned task count: {managed}")
        for unit in timers:
            after = state(unit + ".timer", "ActiveState,UnitFileState")
            if after.get("ActiveState") != "inactive" or after.get("UnitFileState") != "disabled":
                raise RuntimeError(f"old timer still owns scheduling: {unit}")
        (backup / "complete.json").write_text(json.dumps({"finished_at": datetime.now(timezone.utc).isoformat(), "managed_tasks": managed}, indent=2))
        print(f"Handoff complete: {managed} tasks. Backup: {backup}")
    except Exception:
        subprocess.run(["systemctl", "disable", "--now", "news-claw.service"], capture_output=True, timeout=150)
        for path in original_files:
            shutil.copy2(backup / path.name, path)
        with sqlite3.connect(backup / "news.sqlite3") as src, sqlite3.connect(DB) as dst:
            src.backup(dst)
        for target, original in old_units.items():
            target = Path(target)
            if original is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(original)
        command("systemctl", "daemon-reload")
        for unit, info in timers.items():
            if info.get("UnitFileState") == "enabled":
                command("systemctl", "enable", unit + ".timer")
            if info.get("ActiveState") == "active":
                command("systemctl", "start", unit + ".timer")
        raise


if __name__ == "__main__":
    main()
