"""Publication calendar and dated evidence for the Friday and Sunday editions."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def calendar(config, day):
    policy = config.get('workflow', {}).get('publication_calendar')
    if not policy or day < date.fromisoformat(policy['effective_from']):
        return None
    return policy


def edition(config, day):
    policy = calendar(config, day)
    if not policy:
        return None
    for item in policy['editions']:
        if item['weekday'] == day.isoweekday():
            start = day - timedelta(days=(day.isoweekday() - item['window_start_weekday']) % 7)
            source_start = day - timedelta(days=(day.isoweekday() - item.get('source_window_start_weekday', item['window_start_weekday'])) % 7)
            return {**item, 'window_start': start.isoformat(), 'window_end': day.isoformat(),
                    'source_window_start': source_start.isoformat(),
                    'timezone': config['timezone']}
    return None


def off_day(config, day):
    """Return a successful no-op before any source reads, model calls or recovery."""
    policy = calendar(config, day)
    if not policy or edition(config, day):
        return None
    next_day = next(day + timedelta(days=n) for n in range(1, 8)
                    if edition(config, day + timedelta(days=n)))
    return {'success': True, 'business_status': 'not_publication_day',
            'day': day.isoformat(), 'next_publication_day': next_day.isoformat(),
            'needs_attention': False, 'model_called': False, 'network_requests': 0}


def period_source_ids(packet, *, min_body_chars=1000):
    """Only dated, complete bodies qualify; fetching an old page is not new evidence."""
    issue = packet.get('edition')
    if not issue:
        return set()
    bodies = {sid for item in packet['evidence']
              if item.get('record_type') == 'webpage' and len(item.get('text', '').strip()) >= min_body_chars
              for sid in item.get('source_ids', [])}
    ids = set()
    for source in packet['sources']:
        raw = source.get('source_date') or ''
        try:
            stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            day = stamp.astimezone(ZoneInfo(issue['timezone'])).date() if stamp.tzinfo else stamp.date()
        except (ValueError, TypeError):
            continue
        if (source['id'] in bodies and source.get('evidence_level') == 'cached_webpage'
                and issue.get('source_window_start', issue['window_start']) <= day.isoformat() <= issue['window_end']):
            ids.add(source['id'])
    return ids


def validate_edition_plan(plan, packet):
    if not packet.get('edition') or plan['status'] != 'ready':
        return
    chosen = next(item for item in plan['candidates'] if item['id'] == plan['selected_candidate_id'])
    cited = {ref['source_id'] for section in plan['outline']['sections'] for ref in section['evidence_refs']}
    if not (period_source_ids(packet) & set(chosen['source_ids']) & cited):
        raise ValueError('Selected edition needs a cited full source published within its coverage window')
