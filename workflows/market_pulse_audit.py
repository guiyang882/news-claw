"""Read-only coverage audit for the market homepage. No collection or model calls."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone

COMPANIES = ('rocket_lab', 'spacex', 'tesla', 'google', 'amazon', 'coinbase', 'nvidia', 'tsmc')


def age_hours(value, now):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (now - date).total_seconds() / 3600
    except (TypeError, ValueError, AttributeError):
        return None


def assess(news, last_collections, *, now=None):
    now = now or datetime.now(timezone.utc)
    companies, issues = [], []
    for company in COMPANIES:
        events = [event for event in news.get('events', []) if event['company'] == company
                  and (age := age_hours(event.get('published_at'), now)) is not None and age >= 0]
        events.sort(key=lambda event: event['published_at'], reverse=True)
        latest = events[0] if events else None
        recent = [event for event in events if age_hours(event['published_at'], now) <= 168]
        snapshot = news.get('company_briefs', {}).get(company, news.get('analysis', {}))
        analysis = snapshot.get('analysis') or next((item for item in snapshot.get('companies', []) if item['company'] == company), None)
        brief_age = age_hours(snapshot.get('generated_at'), now)
        collected_age = age_hours(last_collections.get(company), now)
        flags = []
        if collected_age is None or collected_age < 0 or collected_age > 24:
            flags.append('collection_not_successful_within_24h')
        if not events:
            flags.append('no_source_records')
        if snapshot.get('status') == 'invalid':
            flags.append('invalid_brief')
        elif recent and (not analysis or brief_age is None or brief_age < 0):
            flags.append('brief_missing_for_recent_sources')
        elif recent and brief_age > 48 and any(age_hours(event['published_at'], now) < brief_age for event in recent):
            flags.append('brief_behind_recent_sources_over_48h')
        if flags:
            issues.append({'company': company, 'reasons': flags})
        companies.append({'company': company, 'latest_source_at': latest['published_at'] if latest else None,
                          'recent_source_count': len(recent), 'brief_at': snapshot.get('generated_at'),
                          'brief_status': snapshot.get('status', 'waiting'),
                          'last_collection_success_at': last_collections.get(company),
                          'coverage': 'recent_sources' if recent else 'no_recent_sources',
                          'needs_attention': bool(flags)})
    return {'success': not issues, 'business_status': 'needs_attention' if issues else 'coverage_checked',
            'checked_at': now.isoformat(), 'companies': companies, 'issues': issues,
            'needs_attention': bool(issues), 'model_calls': 0, 'external_source_requests': 0}


def last_collections(db):
    result = {}
    with sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True) as connection:
        for company in COMPANIES:
            task = 'stocks-quant-market-news-refresh' if company in COMPANIES[:3] else f'company-{company}-news'
            row = connection.execute("SELECT MAX(finished_at) FROM task_runs WHERE task_id=? AND status='succeeded'", (task,)).fetchone()
            result[company] = row[0] if row else None
    return result


def main():
    root = Path(os.environ.get('NEWS_CLAW_ROOT', Path(__file__).resolve().parents[1]))
    config_path = Path(os.environ.get('NEWS_CLAW_TASK_CONFIG_PATH', root / 'config/tasks/market-pulse-coverage-audit.json'))
    config = json.loads(config_path.read_text())
    settings = config['workflow']
    sys.path.insert(0, settings['website_repo'])
    from web.news import NewsStore
    state = Path(settings['state_root'])
    try:
        news = NewsStore(state / 'news_timeline.json', state / 'news_analysis.json').public_payload()
        result = assess(news, last_collections(os.environ.get('NEWS_CLAW_DB', root / 'data/db/news.sqlite3')))
        # Probe only local services through the established maintenance helper.
        from workflows.website_maintenance import health_probe
        result['website_health'] = health_probe(settings['website_runtime'])
    except Exception as error:
        result = {'success': False, 'business_status': 'audit_failed', 'needs_attention': True, 'error': str(error)}
    if not result['success'] and 'error' not in result:
        result['error'] = '; '.join(item['company'] + ': ' + ', '.join(item['reasons']) for item in result['issues'])
    if os.environ.get('NEWS_CLAW_RESULT_PATH'):
        target = Path(os.environ['NEWS_CLAW_RESULT_PATH'])
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        temporary.replace(target)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
