"""Local-only readiness and delivery checks for the daily blog; never calls models or crawls."""
import argparse
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo


def assess_packet(packet, articles, settings, day):
    """A readiness floor, not a substitute for editorial source/claim review."""
    cutoff=day-timedelta(days=settings['max_source_age_days'])
    used_cutoff=day-timedelta(days=settings['recent_publication_days'])
    used={source['url'] for article in articles
          if used_cutoff.isoformat() <= article['published_at'] <= day.isoformat()
          for source in article.get('sources',[]) if source.get('url')}
    bodies={sid for item in packet['evidence']
            if item.get('record_type')=='webpage' and len(item.get('text','').strip())>=settings['min_body_chars']
            for sid in item.get('source_ids',[])}
    urls=set()
    for source in packet['sources']:
        try:
            stamp=date.fromisoformat((source.get('source_date') or '')[:10])
        except ValueError:
            continue
        if (source.get('evidence_level')=='cached_webpage' and source['id'] in bodies
                and cutoff<=stamp<=day):
            urls.add(source['url'])
    unused=urls-used
    reasons=[]
    if len(urls)<settings['min_complete_sources']:
        reasons.append('not_enough_recent_full_bodies')
    if len(unused)<settings['min_unused_sources']:
        reasons.append('no_unused_recent_full_body')
    return {'ready':not reasons,'reasons':reasons,'complete_source_count':len(urls),
            'unused_source_count':len(unused),'source_urls':sorted(urls),'unused_source_urls':sorted(unused)}

def upstream_state(db, task_id, day, zone):
    with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True)) as connection:
        task=connection.execute('SELECT enabled FROM tasks WHERE id=?',(task_id,)).fetchone()
        if not task or not task[0]:
            return {'ready':False,'reason':'upstream_disabled_or_missing','task_id':task_id}
        rows=connection.execute('SELECT id,status,started_at,finished_at,metadata_json FROM task_runs WHERE task_id=? ORDER BY created_at DESC LIMIT 100',(task_id,)).fetchall()
    for run_id,status,started,finished,metadata in rows:
        if not started:
            continue
        stamp=datetime.fromisoformat(started.replace('Z','+00:00'))
        if stamp.tzinfo is None or stamp.astimezone(zone).date()!=day:
            continue
        result=json.loads(metadata or '{}').get('result',{})
        ready=(status=='succeeded' and bool(finished) and result.get('success') is True)
        return {'ready':ready,'reason':'upstream_ready' if ready else 'upstream_not_successful',
                'task_id':task_id,'run_id':run_id,'status':status,
                'business_status':result.get('business_status'),'finished_at':finished}
    return {'ready':False,'reason':'upstream_not_run_today','task_id':task_id}

def preflight(config, root, db, day, *, packet=None):
    from . import daily_blog as blog
    sys.path.insert(0,config['workflow']['website_repo'])
    from web.blog_runtime import load_runtime_articles
    articles=load_runtime_articles(Path(config['workflow']['website_state']))
    if any(article['published_at']==day.isoformat() for article in articles):
        return {'success':True,'business_status':'already_published','day':day.isoformat(),
                'model_called':False,'network_requests':0}
    settings=config['workflow']['readiness']
    upstream=upstream_state(db,settings['upstream_task_id'],day,ZoneInfo(config['timezone']))
    packet=packet if packet is not None else blog.collect_packet(config,root,db,day,include_media=False)
    evidence=assess_packet(packet,articles,settings,day)
    ready=upstream['ready'] and evidence['ready']
    return {'success':ready,'business_status':'evidence_ready' if ready else 'preflight_blocked',
            'day':day.isoformat(),'needs_attention':not ready,'upstream':upstream,'evidence':evidence,
            'packet_sha256':blog.digest(packet),'model_called':False,'network_requests':0,
            'next_action':('Proceed to independent topic and fact review' if ready else
                           'Inspect upstream run and cached bodies; scheduled second slot may start only before any model attempt. Do not reset denials or fabricate evidence.')}

def inspect_delivery(config, root, db, day):
    from . import daily_blog as blog
    sys.path.insert(0,config['workflow']['website_repo'])
    from web.blog_runtime import load_runtime_articles
    # Hash validation is part of load_runtime_articles; a mere day marker is not publication.
    articles=load_runtime_articles(Path(config['workflow']['website_state']))
    published=[item for item in articles if item['published_at']==day.isoformat()]
    if published:
        surfaces=None
        if config['workflow'].get('delivery_surfaces',{}).get('enabled'):
            from .publication_surfaces import inspect_surfaces
            surfaces=inspect_surfaces([item['slug'] for item in published],config['workflow']['delivery_surfaces'])
        healthy=surfaces is None or surfaces['success']
        return {'success':healthy,'business_status':'publication_verified' if healthy else 'publication_surface_mismatch','day':day.isoformat(),
                'slug':published[0]['slug'],'bilingual_sources_validated':True,'surfaces':surfaces,
                'model_called':False,'network_requests':0,'local_http_requests':surfaces['local_http_requests'] if surfaces else 0,
                'needs_attention':not healthy}
    marker=root/'data/runs/daily-blog-days'/(day.isoformat()+'.json')
    previous=blog.read_json(marker) if marker.exists() else None
    readiness=preflight(config,root,db,day)
    return {'success':False,'business_status':'daily_publication_missing','day':day.isoformat(),
            'needs_attention':True,'attempt':previous,'readiness':readiness,
            'model_called':False,'network_requests':0,
            'next_action':('Inspect the saved attempt/checkpoints and remaining daily model budget; manual review is required before resuming.'
                           if previous else 'No model attempt was reserved. Resolve the readiness failure before manually queuing the writer.')}

def main():
    from . import daily_blog as blog
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',default=os.environ.get('NEWS_CLAW_TASK_ID','daily-blog-readiness'))
    parser.add_argument('--check',action='store_true',help='Local preview only; no models, fetches, or enqueue')
    args=parser.parse_args()
    root=Path(os.environ.get('NEWS_CLAW_ROOT',blog.ROOT)).resolve()
    db=Path(os.environ.get('NEWS_CLAW_DB',root/'data/db/news.sqlite3')).resolve()
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as connection:
        row=connection.execute('SELECT config_json,enabled FROM tasks WHERE id=?',(args.task,)).fetchone()
        if not row:
            parser.error('Unknown check task')
        task=blog.read_json(Path(os.environ['NEWS_CLAW_TASK_CONFIG_PATH'])) if os.environ.get('NEWS_CLAW_TASK_CONFIG_PATH') else json.loads(row[0])
        if not args.check:
            active=connection.execute("SELECT 1 FROM task_runs WHERE id=? AND task_id=? AND status='running'",
                                      (os.environ.get('NEWS_CLAW_RUN_ID'),args.task)).fetchone()
            if not row[1] or not active:
                parser.error('Launch enabled checks through news-claw')
        writer=connection.execute('SELECT config_json,enabled FROM tasks WHERE id=?',(task['workflow']['blog_task_id'],)).fetchone()
    try:
        if not writer or not writer[1]:
            raise ValueError('Blog writer is disabled or missing')
        config=json.loads(writer[0])
        config['workflow']['delivery_surfaces']=task['workflow'].get('delivery_surfaces',{})
        day=datetime.now(ZoneInfo(config['timezone'])).date()
        if task['workflow']['mode']=='readiness':
            result=preflight(config,root,db,day)
        elif task['workflow']['mode']=='delivery':
            result=inspect_delivery(config,root,db,day)
        else:
            raise ValueError('Unsupported blog check mode')
    except Exception as error:
        result={'success':False,'business_status':'blog_check_failed','needs_attention':True,
                'error':str(error),'model_called':False,'network_requests':0}
    result['checked_at']=datetime.now(timezone.utc).isoformat()
    if not args.check and os.environ.get('NEWS_CLAW_RESULT_PATH'):
        blog.atomic_json(Path(os.environ['NEWS_CLAW_RESULT_PATH']),result)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['success'] else 1

if __name__=='__main__':
    raise SystemExit(main())
