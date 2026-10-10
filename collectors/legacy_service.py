"""Run an existing oneshot service under the Go engine's queue and audit."""

import argparse
import fcntl
import json
import os
import shlex
import signal
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

from collectors.news import atomic_json, load_state, policy_paths, utcnow

UNITS = {
    "quant-news-refresh.service", "quant-news-analysis.service",
    "quant-optimus-supply-review.service", "quant-company-pulses-review.service",
    "quant-tech-history-review.service", "quant-market-temperature.service",
    "quant-blog-compose.service", "quant-blog-daily.service",
}


def unit_state(unit):
    result = subprocess.run(["systemctl", "show", unit, "--property=ActiveState,Result,ExecMainStatus"],
                            capture_output=True, text=True, check=True, timeout=10)
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def stop_unit(unit):
    subprocess.run(["systemctl", "stop", "--no-block", unit], check=True, timeout=10)
    deadline = time.monotonic() + 100
    while unit_state(unit).get("ActiveState") in {"active", "activating", "deactivating", "reloading"}:
        if time.monotonic() > deadline:
            raise TimeoutError(f"service did not stop: {unit}")
        time.sleep(0.25)


def prepare_codex_input(root, unit, task):
    """Forward the queued configuration to a legacy service without global env changes."""
    if not task.get("workflow", {}).get("codex"):
        return
    path = root / "data/runs/service-inputs" / (unit + ".json")
    configured = subprocess.run(["systemctl", "show", unit, "--property=Environment", "--value"],
                                capture_output=True, text=True, check=True, timeout=10)
    environment = dict(value.split("=", 1) for value in shlex.split(configured.stdout) if "=" in value)
    if environment.get("NEWS_CLAW_TASK_CONFIG_PATH") != str(path):
        raise RuntimeError("Install the Codex task-input service override before running " + unit)
    atomic_json(path, task)
    os.chmod(path, 0o600)


def reserve_google(root, policy, interrupted):
    state_path, lock_path = policy_paths(root, "google")
    with lock_path.open("a") as lock:
        while True:
            if interrupted():
                raise InterruptedError("engine stopped")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(0.1)
                continue
            state = load_state(state_path)
            if state.get("blocked"):
                raise RuntimeError("shared Google circuit is open")
            for path in policy.get("shared_circuit_paths", []):
                if load_state(Path(path)).get("open"):
                    raise RuntimeError("legacy Google circuit is open")
            earliest = max(float(state.get("last_request_at", 0)) + max(60, float(state.get("interval", 0))),
                           float(state.get("not_before", 0)))
            remaining = earliest - time.time()
            if remaining > 0:
                fcntl.flock(lock, fcntl.LOCK_UN)
                time.sleep(min(remaining, 1))
                continue
            atomic_json(state_path, {**state, "source": "google", "last_request_at": time.time(), "interval": 60})
            return


def finish_google(root, policy):
    # The old service retains its own per-request limiter (>=60s). Reserve a
    # conservative boundary after it completes so the next crawler cannot burst.
    state_path, lock_path = policy_paths(root, "google")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_state(state_path)
        state.update(source="google", last_request_at=time.time(), interval=60)
        for path in policy.get("shared_circuit_paths", []):
            legacy = load_state(Path(path))
            if legacy.get("open"):
                state.update(blocked="legacy source circuit: " + legacy.get("reason", "denied"), blocked_at=utcnow())
        atomic_json(state_path, state)


def record_business_result(unit, started, result):
    """Keep the business outcome distinct from successful process completion."""
    journal = subprocess.run(["journalctl", "--unit", unit, "--since", f"@{started:.6f}",
                              "--no-pager", "--output=cat", "--lines=200"],
                             timeout=10, check=False, capture_output=True, text=True)
    print(journal.stdout, end="", flush=True)
    if journal.returncode:
        result["journal_error"] = journal.stderr.strip()
        return
    # Only the blog adapters emit a single JSON business result. Model responses
    # in other workers' journals must not be interpreted as their terminal state.
    if unit not in {"quant-blog-compose.service", "quant-blog-daily.service"}:
        return
    for line in reversed(journal.stdout.splitlines()):
        try:
            payload = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("status"), str) and "day" in payload:
            result["business_status"] = payload["status"]
            result["business_result"] = payload
            if payload["status"] in {"model_provider_blocked", "previous_attempt_failed"}:
                result.update(success=False, error=payload["status"])
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True, choices=sorted(UNITS))
    args = parser.parse_args()
    root = Path(os.environ["NEWS_CLAW_ROOT"])
    task = json.loads(Path(os.environ["NEWS_CLAW_TASK_CONFIG_PATH"]).read_text())
    if task.get("execution", {}).get("systemd_unit") != args.unit:
        parser.error("service unit does not match the queued task snapshot")
    with closing(sqlite3.connect(Path(os.environ["NEWS_CLAW_DB"]).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if not db.execute("SELECT 1 FROM task_runs WHERE id=? AND task_id=? AND status='running'",
                          (os.environ["NEWS_CLAW_RUN_ID"], os.environ["NEWS_CLAW_TASK_ID"])).fetchone():
            parser.error("launch through the Go engine")
    cancelled = False

    def interrupt(*_):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    started = time.time()
    launched = False
    reserved = False
    process = None
    result = {"success": False, "systemd_unit": args.unit, "items_seen": 0, "items_new": 0}
    policy = task.get("collector", {}).get("request_policy", {})
    google = task.get("collector", {}).get("type") == "google_news_rss"
    try:
        if unit_state(args.unit).get("ActiveState") not in {"inactive", "failed"}:
            raise RuntimeError("service is already running outside this task; inspect ownership")
        if google:
            reserve_google(root, policy, lambda: cancelled)
            reserved = True
        if cancelled:
            raise InterruptedError("engine stopped")
        prepare_codex_input(root, args.unit, task)
        launched = True
        # systemctl start waits for a oneshot job to complete.
        process = subprocess.Popen(["systemctl", "start", args.unit])
        while process.poll() is None and not cancelled:
            time.sleep(0.25)
        if cancelled:
            raise InterruptedError("engine stopped")
        state = unit_state(args.unit)
        result["service_result"] = state
        if process.returncode != 0 or state.get("Result") != "success" or state.get("ExecMainStatus") != "0":
            raise RuntimeError(f"legacy service failed: {state}")
        result["success"] = True
    except Exception as error:
        result["error"] = str(error)
        if launched and (cancelled or unit_state(args.unit).get("ActiveState") in {"active", "activating", "deactivating"}):
            try:
                stop_unit(args.unit)
            except Exception as stop_error:
                result["stop_error"] = str(stop_error)
                result["recovery_required"] = True
    finally:
        if process is not None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if reserved:
            try:
                finish_google(root, policy)
            except Exception as error:
                result.update(success=False, error=f"shared request policy update failed: {error}")
        if launched:
            try:
                record_business_result(args.unit, started, result)
            except Exception as error:
                result["journal_error"] = str(error)
        result["finished_at"] = utcnow()
        atomic_json(Path(os.environ["NEWS_CLAW_RESULT_PATH"]), result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
