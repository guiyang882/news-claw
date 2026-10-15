"""Bounded official relationship-page discovery; use the existing shared rate/circuit controls."""
import argparse
import hashlib
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import sqlite3
import subprocess
import sys
from collectors.blog_evidence import select_sources, permitted
from collectors.news import atomic_json


def select_relationship_sources(config, root, db, now):
    """Reserve half the budget for reviewed URLs missing from RSS; no network here."""
    settings = config['collector']['discovery']
    limit = min(4, settings['max_pages_per_run'])
    selected = select_sources(config, root, db, now)[:max(1, limit // 2)]
    seen = {item['url'] for item in selected}
    counts = {}
    for item in selected:
        host = urlsplit(item['url']).hostname
        counts[host] = counts.get(host, 0) + 1
    with closing(sqlite3.connect(db)) as connection:
        connection.row_factory = sqlite3.Row
        for item in settings.get('reviewed_pages', []):
            if len(selected) >= limit:
                break
            url = item['url']
            if url in seen or not permitted(url, settings['official_url_prefixes']):
                continue
            if not item.get('published_at') or item['published_at'] > now.isoformat():
                continue
            cached = False
            for row in connection.execute('SELECT normalized_path, content_hash FROM documents WHERE canonical_url=?', (url,)):
                path = (root / (row['normalized_path'] or '')).resolve()
                if not path.is_relative_to((root/'data/normalized').resolve()) or not path.is_file():
                    continue
                record = json.loads(path.read_text())
                digest = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                if digest != row['content_hash']:
                    raise ValueError('Reviewed-page cache hash mismatch')
                if record.get('record_type') == 'webpage' and len(record.get('text', '')) >= 1000:
                    cached = True
                    break
            host = urlsplit(url).hostname
            if cached or counts.get(host, 0) >= settings['max_pages_per_host']:
                continue
            selected.append({**item, 'type': 'page', 'language': 'en', 'obey_robots_txt': True,
                             'minimum_text_chars': 1000})
            seen.add(url)
            counts[host] = counts.get(host, 0) + 1
    return selected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    root=Path(os.environ.get('NEWS_CLAW_ROOT',Path(__file__).resolve().parents[1]))
    db=Path(os.environ.get('NEWS_CLAW_DB',root/'data/db/news.sqlite3'))
    config=json.loads(Path(os.environ.get('NEWS_CLAW_TASK_CONFIG_PATH',root/'config/tasks/company-dependencies-evidence.json')).read_text())
    selected=select_relationship_sources(config,root,db,datetime.now(timezone.utc))
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
