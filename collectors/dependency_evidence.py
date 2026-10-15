"""Bounded official relationship-page discovery; use the existing shared rate/circuit controls."""
import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from collectors.blog_evidence import select_sources
from collectors.news import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    root=Path(os.environ.get('NEWS_CLAW_ROOT',Path(__file__).resolve().parents[1]))
    db=Path(os.environ.get('NEWS_CLAW_DB',root/'data/db/news.sqlite3'))
    config=json.loads(Path(os.environ.get('NEWS_CLAW_TASK_CONFIG_PATH',root/'config/tasks/company-dependencies-evidence.json')).read_text())
    selected=select_sources(config,root,db,datetime.now(timezone.utc))
    if not args.execute:
        print(json.dumps({'sources':selected,'requests':0},ensure_ascii=False));return 0
    run_id=os.environ.get('NEWS_CLAW_RUN_ID')
    with closing(sqlite3.connect(db)) as connection:
        if not connection.execute("SELECT 1 FROM task_runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=? AND r.task_id=? AND r.status='running' AND t.enabled=1",(run_id,config['id'])).fetchone():
            raise ValueError('Launch through news-claw engine')
    if not selected:
        atomic_json(Path(os.environ['NEWS_CLAW_RESULT_PATH']),{'success':True,'business_status':'no_new_official_pages','items_seen':0,'items_new':0,'requests_made':0});return 0
    resolved=deepcopy(config);resolved['collector']['sources']=selected
    path=root/'data/runs'/run_id/'resolved-evidence-task.json'
    atomic_json(path,resolved)
    # Shared HTTP cache, global >=10 second pacing, robots, persistent denial circuits and no retries.
    return subprocess.run([sys.executable,'-m','collectors.news'],env={**os.environ,'NEWS_CLAW_TASK_CONFIG_PATH':str(path),'NEWS_CLAW_SERIAL_REQUESTS':'1'}).returncode


if __name__=='__main__':raise SystemExit(main())
