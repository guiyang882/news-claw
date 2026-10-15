"""Resolve a bounded official-page reading list from cached feeds, then use news safety controls."""
from contextlib import closing
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.parse import urlsplit


def permitted(url, prefixes):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment and parsed.port in (None, 443)
            and any(parsed.netloc == urlsplit(prefix).netloc and parsed.path.startswith(urlsplit(prefix).path)
                    for prefix in prefixes))


def select_sources(task, root, db, now):
    settings = task['collector']['discovery']
    limit = min(6, settings['max_pages_per_run'])
    cutoff = (now - timedelta(days=settings['lookback_days'])).isoformat()
    prefixes = settings['official_url_prefixes']
    keywords = re.compile(settings['title_pattern'], re.I)
    candidates, cached_urls, seen, counts = [], set(), set(), {}
    with closing(sqlite3.connect(db)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute('SELECT * FROM documents WHERE COALESCE(published_at,fetched_at)>=? ORDER BY COALESCE(published_at,fetched_at) DESC, fetched_at DESC LIMIT 1500', (cutoff,)).fetchall()
    # Validate records before allowing them to influence discovery or cache reuse.
    valid=[]
    for row in rows:
        url=row['canonical_url']
        if not permitted(url,prefixes):
            continue
        path=(root/(row['normalized_path'] or '')).resolve()
        if not path.is_relative_to((root/'data/normalized').resolve()) or not path.is_file():
            continue
        record=json.loads(path.read_text())
        digest=hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if digest!=row['content_hash']:
            raise ValueError('Evidence discovery cache hash mismatch')
        if record['record_type']=='webpage' and len(record['text'])>=1000:
            cached_urls.add(url)
        valid.append((row,record))
    for row,record in valid:
        url=row['canonical_url']
        if url in seen or url in cached_urls or record['record_type']!='feed_entry':
            continue
        stamp=row['published_at']
        if not stamp or not cutoff <= stamp <= now.isoformat():
            continue
        source=json.loads(row['source_json'])
        if source.get('type') not in {'rss','atom'} or urlsplit(source.get('url','')).hostname not in settings['official_feed_hosts']:
            continue
        if not keywords.search(row['title']):
            continue
        seen.add(url)
        host=urlsplit(url).hostname
        if counts.get(host,0)>=settings['max_pages_per_host']:
            continue
        counts[host]=counts.get(host,0)+1
        candidates.append({'name':source.get('name',host)+' — article body','type':'page','url':url,
                           'language':row['language'] or 'en','obey_robots_txt':True,
                           'published_at':stamp,'discovered_from':source['url'],'discovery_document_id':row['id'],
                           'minimum_text_chars':1000})
        if len(candidates)>=limit:
            break
    return candidates


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    root=Path(os.environ.get('NEWS_CLAW_ROOT',Path(__file__).resolve().parents[1])).resolve()
    db=Path(os.environ.get('NEWS_CLAW_DB',root/'data/db/news.sqlite3'))
    snapshot=os.environ.get('NEWS_CLAW_TASK_CONFIG_PATH')
    config=json.loads(Path(snapshot or root/'config/tasks/daily-blog-primary-evidence.json').read_text())
    selected=select_sources(config,root,db,datetime.now(timezone.utc))
    if args.check:
        print(json.dumps({'sources':selected,'network_requests':0},ensure_ascii=False))
        return 0
    run_id=os.environ.get('NEWS_CLAW_RUN_ID','')
    with closing(sqlite3.connect(db)) as connection:
        if not connection.execute("SELECT 1 FROM task_runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=? AND r.task_id=? AND r.status='running' AND t.enabled=1",(run_id,config['id'])).fetchone():
            raise ValueError('Launch evidence collection through the news-claw engine')
    resolved=deepcopy(config)
    resolved['collector']['sources']=selected
    path=root/'data/runs'/run_id/'resolved-evidence-task.json'
    path.write_text(json.dumps(resolved,ensure_ascii=False,indent=2)+'\n')
    if not selected:
        result={'success':True,'business_status':'no_new_official_pages','items_seen':0,'items_new':0,'requests_made':0}
        Path(os.environ['NEWS_CLAW_RESULT_PATH']).write_text(json.dumps(result)+'\n')
        print(json.dumps(result))
        return 0
    env={**os.environ,'NEWS_CLAW_TASK_CONFIG_PATH':str(path)}
    return subprocess.run([sys.executable,'-m','collectors.news'],env=env).returncode

if __name__=='__main__':
    raise SystemExit(main())
