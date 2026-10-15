"""Cache unadjusted CSI300 daily bars; connect only with an explicit access decision."""
import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import time
from unittest.mock import patch
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ENDPOINT = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
FIELDS = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume_shares', 'amount_cny', 'source', 'adjustment']


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def read(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def normalize(frame, symbol, start, end):
    """Eastmoney documents volume in lots (100 shares), amount in CNY."""
    required = ['日期', '开盘', '最高', '最低', '收盘', '成交量', '成交额']
    if frame.empty or any(k not in frame.columns for k in required):
        raise ValueError('empty_or_incomplete_data')
    rows = []
    seen = set()
    for raw in frame.to_dict('records'):
        day = date.fromisoformat(str(raw['日期'])[:10])
        if not start <= day <= end or day in seen:
            raise ValueError('duplicate_or_out_of_range_date')
        seen.add(day)
        values = [float(raw[k]) for k in required[1:]]
        o, h, l, c, v, a = values
        if not all(math.isfinite(x) for x in values) or min(o, h, l, c) <= 0 or min(v, a) < 0:
            raise ValueError('invalid_numeric_data')
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError('invalid_ohlc_bounds')
        shares = v * 100
        if not math.isclose(shares, round(shares), abs_tol=1e-5):
            raise ValueError('invalid_volume_unit')
        rows.append(dict(zip(FIELDS, [symbol, day.isoformat(), o, h, l, c, round(shares), a, 'eastmoney_via_akshare', 'none'])))
    return sorted(rows, key=lambda row: row['date'])


def access_gate(config, universe, target):
    review = config['collector']['access_review']
    policy = config['collector']['request_policy']
    if review.get('endpoint') != ENDPOINT:
        raise ValueError('provider_access_and_quota_unconfirmed')
    if review.get('status') == 'user_authorized_conservative_access':
        if not review.get('user_instruction') or review.get('provider_quota_confirmed') is not False:
            raise ValueError('missing_explicit_user_access_decision')
        if policy['min_interval_seconds'] < 60 or not 0 < policy['max_requests_per_day'] <= 300:
            raise ValueError('exceeds_conservative_user_limit')
    elif review.get('status') == 'approved':
        if not review.get('evidence_reference') or not review.get('reviewed_by'):
            raise ValueError('missing_provider_evidence')
        if date.fromisoformat(review['valid_until']) < target:
            raise ValueError('access_review_expired')
        if policy['min_interval_seconds'] < max(60, review['minimum_interval_seconds']):
            raise ValueError('interval_exceeds_approved_rate')
        if not 0 < policy['max_requests_per_day'] <= review['max_requests_per_day']:
            raise ValueError('daily_budget_exceeds_authorization')
    else:
        raise ValueError('provider_access_and_quota_unconfirmed')
    if not universe.get('verified_current') or date.fromisoformat(universe['valid_through']) < target:
        raise ValueError('csi300_membership_needs_current_verification')
    symbols = universe['symbols']
    if len(set(symbols)) != 300 or any(len(s) != 6 or not s.isdigit() for s in symbols):
        raise ValueError('invalid_csi300_universe')


class Guard:
    def __init__(self, state, policy, run_limit):
        self.state, self.policy, self.run_limit = state, policy, run_limit
        self.count = 0
        self.receipts = []

    def block(self, reason):
        save(self.state / 'circuit.json', {'open': True, 'reason': reason, 'at': datetime.now(timezone.utc).isoformat(), 'automatic_retry': False})

    def get(self, url, **kwargs):
        import requests
        if url != ENDPOINT or kwargs.get('params', {}).get('fqt') != '0':
            raise ValueError('unexpected_endpoint_or_adjustment')
        if read(self.state / 'circuit.json', {}).get('open'):
            raise ValueError('source_circuit_open')
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        pacing = read(self.state / 'pacing.json', {})
        used = pacing.get('count', 0) if pacing.get('day') == today else 0
        if self.count >= self.run_limit or used >= self.policy['max_requests_per_day']:
            raise ValueError('request_budget_exhausted')
        time.sleep(max(0, pacing.get('last_request', 0) + self.policy['min_interval_seconds'] - time.time()))
        save(self.state / 'pacing.json', {'day': today, 'count': used + 1, 'last_request': time.time()})
        self.count += 1
        receipt = {'url': url, 'params': kwargs['params'], 'at': datetime.now(timezone.utc).isoformat()}
        self.receipts.append(receipt)
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(url, params=kwargs['params'], timeout=20, allow_redirects=False)
            receipt['http_status'] = response.status_code
            if response.status_code != 200:
                raise ValueError('non_200_response')
            body = response.content
            digest = hashlib.sha256(body).hexdigest()
            path = self.state / 'raw' / (digest + '.json')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            receipt.update(sha256=digest, raw_path=str(path))
            payload = response.json()
            if payload.get('rc') != 0 or not payload.get('data', {}).get('klines'):
                raise ValueError('denial_or_empty_response')
            return response
        except Exception as exc:
            receipt['error_type'] = type(exc).__name__
            self.block('network_or_response_failure_requires_review')
            raise


def run(config, universe, state, execute=False, run_limit=1, target=None):
    target = target or datetime.now(ZoneInfo('Asia/Shanghai')).date() - timedelta(days=1)
    result = {'success': True, 'business_status': 'preview', 'network_requests_made': 0,
              'universe_size': len(universe['symbols']), 'membership_as_of': universe['as_of'],
              'membership_verified_current': universe['verified_current'], 'through': target.isoformat(),
              'items_seen': 0, 'items_new': 0}
    try:
        access_gate(config, universe, target)
    except (ValueError, KeyError) as exc:
        result.update(business_status='blocked', block_reason=str(exc), success=not execute)
        return result
    if not execute:
        return result
    policy = config['collector']['request_policy']
    if not 1 <= run_limit <= policy['max_requests_per_run']:
        raise ValueError('invalid_request_budget')
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'collector.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if read(state / 'circuit.json', {}).get('open'):
            return {**result, 'success': False, 'business_status': 'blocked', 'block_reason': 'source_circuit_open'}
        import akshare as ak
        guard = Guard(state, policy, run_limit)
        progress = read(state / 'progress.json', {})
        try:
            for symbol in universe['symbols']:
                previous = progress.get(symbol)
                start = date.fromisoformat(previous['checked_through']) + timedelta(days=1) if previous else date.fromisoformat(config['collector']['initial_start_date'])
                cache = state / 'bars' / (symbol + '.csv')
                if previous and (not cache.exists() or hashlib.sha256(cache.read_bytes()).hexdigest() != previous['sha256']):
                    raise ValueError('cache_integrity_failure')
                if start > target:
                    continue
                if guard.count >= run_limit:
                    break
                with patch('requests.get', guard.get):
                    frame = ak.stock_zh_a_hist(symbol=symbol, period='daily', start_date=start.strftime('%Y%m%d'), end_date=target.strftime('%Y%m%d'), adjust='', timeout=20)
                rows = normalize(frame, symbol, start, target)
                # A source lag is visible; never advance through dates absent from the response.
                existing = list(csv.DictReader(io.StringIO(cache.read_text()))) if cache.exists() else []
                data = io.StringIO()
                writer = csv.DictWriter(data, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(existing + rows)
                cache.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache.with_suffix('.tmp')
                temporary.write_text(data.getvalue())
                temporary.replace(cache)
                progress[symbol] = {'checked_through': rows[-1]['date'], 'sha256': hashlib.sha256(cache.read_bytes()).hexdigest()}
                save(state / 'progress.json', progress)
                result['items_seen'] += len(rows)
                result['items_new'] += len(rows)
            result['business_status'] = 'downloaded' if result['items_new'] else 'cache_current'
        except Exception as exc:
            guard.block('collection_failure_requires_review')
            result.update(success=False, business_status='blocked', error_type=type(exc).__name__)
        finally:
            result['symbols_current'] = sum(v['checked_through'] >= target.isoformat() for v in progress.values())
            result['coverage_complete'] = all(progress.get(s, {}).get('checked_through', '') >= target.isoformat() for s in universe['symbols'])
            result.update(network_requests_made=guard.count, requests=guard.receipts)
            with (state / 'batches.jsonl').open('a') as log:
                log.write(json.dumps(result, ensure_ascii=False) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.environ.get('NEWS_CLAW_TASK_CONFIG_PATH', 'config/tasks/csi300-akshare-daily.json'))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--refresh-membership', action='store_true')
    parser.add_argument('--max-requests', type=int, default=1)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    universe = json.loads(Path(config['collector']['universe_path']).read_text())
    target = None
    try:
        if args.refresh_membership and args.execute:
            # Validate access decision before any source request; current-list refresh
            # subsequently validates the actual requested membership/market date.
            access_gate(config, universe, date.fromisoformat(universe['as_of']))
            from collectors.csi300_membership import refresh
            latest_allowed = datetime.now(ZoneInfo('Asia/Shanghai')).date() - timedelta(days=1)
            universe = refresh(Path(config['collector']['state_dir']), latest_allowed)
            target = date.fromisoformat(universe['as_of'])
        result = run(config, universe, Path(config['collector']['state_dir']), args.execute, args.max_requests, target)
    except Exception as exc:
        result = {'success': False, 'business_status': 'blocked', 'block_reason': str(exc),
                  'items_seen': 0, 'items_new': 0, 'stage': 'membership_or_preflight'}
    if os.environ.get('NEWS_CLAW_RESULT_PATH'):
        save(Path(os.environ['NEWS_CLAW_RESULT_PATH']), result)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
