"""Cache one official CSI constituent snapshot per Beijing day; no retries."""
from datetime import date, datetime, timezone
import fcntl
import hashlib
import io
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from collectors.akshare_daily import read, save

URL = 'https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/000300cons.xls'


def validate(frame, target):
    if frame.shape != (300, 9) or frame.isna().any().any():
        raise ValueError('invalid_membership_shape')
    dates = set(frame.iloc[:, 0].astype(str))
    if len(dates) != 1 or set(frame.iloc[:, 1].astype(str).str.zfill(6)) != {'000300'}:
        raise ValueError('invalid_membership_index_or_dates')
    day = datetime.strptime(dates.pop(), '%Y%m%d').date()
    if not 0 <= (target - day).days <= 14:
        raise ValueError('future_or_stale_official_membership')
    symbols = frame.iloc[:, 4].astype(str).str.zfill(6)
    if symbols.nunique() != 300 or not symbols.str.fullmatch(r'\d{6}').all():
        raise ValueError('invalid_membership_symbols')
    for symbol, exchange in zip(symbols, frame.iloc[:, 7]):
        if not ((symbol.startswith('6') and exchange == '上海证券交易所') or
                (symbol.startswith(('0', '3')) and exchange == '深圳证券交易所')):
            raise ValueError('invalid_membership_exchange')
    return day.isoformat(), sorted(symbols.tolist())


def refresh(state, target):
    import pandas as pd
    import requests
    state = Path(state)
    directory = state / 'membership'
    directory.mkdir(parents=True, exist_ok=True)
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    with (directory / 'refresh.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if read(state / 'circuit.json', {}).get('open'):
            raise ValueError('market_source_circuit_open')
        if read(directory / 'circuit.json', {}).get('open'):
            raise ValueError('membership_source_circuit_open')
        receipt_path = directory / (today + '-receipt.json')
        cached = read(receipt_path, {})
        if cached:
            if not cached.get('success'):
                raise ValueError('membership_attempt_already_failed')
            raw = Path(cached['raw_path']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != cached['sha256']:
                raise ValueError('membership_cache_integrity_failure')
        else:
            receipt = {'url': URL, 'at': datetime.now(timezone.utc).isoformat(),
                       'requests': 1, 'automatic_retry': False, 'success': False}
            save(receipt_path, receipt)
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    response = session.get(URL, timeout=30, allow_redirects=False)
                receipt['http_status'] = response.status_code
                if response.status_code != 200:
                    raise ValueError('membership_non_200_response')
                raw = response.content
                if not raw.startswith((bytes.fromhex('d0cf11e0a1b11ae1'), b'PK')):
                    raise ValueError('membership_not_excel')
                validate(pd.read_excel(io.BytesIO(raw), dtype=str), target)
                digest = hashlib.sha256(raw).hexdigest()
                raw_path = directory / (digest + '.xls')
                raw_path.write_bytes(raw)
                receipt.update(success=True, sha256=digest, raw_path=str(raw_path),
                               last_modified=response.headers.get('Last-Modified'))
                save(receipt_path, receipt)
                cached = receipt
            except Exception as exc:
                receipt['error_type'] = type(exc).__name__
                save(receipt_path, receipt)
                save(directory / 'circuit.json', {'open': True, 'reason': str(exc), 'automatic_retry': False})
                raise
        day, symbols = validate(pd.read_excel(io.BytesIO(raw), dtype=str), target)
        universe = {'index': '000300', 'as_of': day, 'valid_through': day,
                    'verified_current': True, 'symbols': symbols,
                    'source_url': URL, 'source_sha256': cached['sha256'], 'checked_on': today}
        save(directory / 'latest.json', universe)
        return universe
