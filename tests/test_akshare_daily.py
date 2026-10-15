import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from collectors.akshare_daily import ENDPOINT, Guard, access_gate, error_details, normalize, run, save


class DailyTest(unittest.TestCase):
    def frame(self):
        return pd.DataFrame([{'日期': '2026-10-08', '开盘': 10, '最高': 12, '最低': 9,
                              '收盘': 11, '成交量': 123, '成交额': 130000}])

    def test_units_and_unadjusted(self):
        row = normalize(self.frame(), '600000', date(2026, 10, 8), date(2026, 10, 9))[0]
        self.assertEqual(row['volume_shares'], 12300)
        self.assertEqual(row['amount_cny'], 130000)
        self.assertEqual(row['adjustment'], 'none')

    def test_bad_values_and_duplicates(self):
        for column, value in [('最高', 8), ('成交量', -1), ('收盘', float('nan'))]:
            frame = self.frame()
            frame[column] = value
            with self.assertRaises(ValueError):
                normalize(frame, '600000', date(2026, 10, 8), date(2026, 10, 9))
        with self.assertRaises(ValueError):
            normalize(pd.concat([self.frame(), self.frame()]), '600000', date(2026, 10, 8), date(2026, 10, 9))

    def test_unapproved_execute_never_imports_or_calls_provider(self):
        config = {'collector': {'access_review': {'status': 'pending'}}}
        universe = {'symbols': ['600000'], 'as_of': '2026-08-31', 'verified_current': False}
        with tempfile.TemporaryDirectory() as td, patch('requests.sessions.Session.request') as request:
            result = run(config, universe, Path(td), execute=True)
            self.assertFalse(result['success'])
            self.assertEqual(result['network_requests_made'], 0)
            request.assert_not_called()
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_user_pause_blocks_manual_execute_without_network(self):
        config = {'collector': {'access_review': {'status': 'paused_by_user'}}}
        universe = {'symbols': [], 'as_of': '2026-10-14', 'verified_current': True}
        with tempfile.TemporaryDirectory() as td, patch('requests.sessions.Session.request') as request:
            result = run(config, universe, Path(td), execute=True)
            self.assertFalse(result['success'])
            self.assertEqual(result['block_reason'], 'collector_paused_by_user')
            request.assert_not_called()

    def test_stale_membership_blocked_even_with_approval(self):
        config = {'collector': {'access_review': {'status': 'approved', 'endpoint': ENDPOINT,
            'evidence_reference': 'test fixture', 'reviewed_by': 'test', 'valid_until': '2026-12-31',
            'minimum_interval_seconds': 60, 'max_requests_per_day': 300},
            'request_policy': {'min_interval_seconds': 60, 'max_requests_per_day': 300}}}
        with self.assertRaisesRegex(ValueError, 'membership'):
            access_gate(config, {'verified_current': False}, date(2026, 10, 14))

    def test_user_activation_preserves_local_caps_and_evidence(self):
        config = {'collector': {'access_review': {
            'status': 'user_authorized_conservative_access', 'endpoint': ENDPOINT,
            'user_instruction': 'explicit activation', 'provider_quota_confirmed': False},
            'request_policy': {'min_interval_seconds': 60, 'max_requests_per_day': 300}}}
        universe = {'verified_current': True, 'valid_through': '2026-10-14',
                    'symbols': [f'{i:06d}' for i in range(300)]}
        access_gate(config, universe, date(2026, 10, 14))
        config['collector']['request_policy']['min_interval_seconds'] = 59
        with self.assertRaisesRegex(ValueError, 'conservative'):
            access_gate(config, universe, date(2026, 10, 14))
        config['collector']['request_policy']['min_interval_seconds'] = 60
        config['collector']['access_review']['provider_quota_confirmed'] = True
        with self.assertRaisesRegex(ValueError, 'explicit'):
            access_gate(config, universe, date(2026, 10, 14))

    def test_denial_opens_persistent_circuit_without_retry(self):
        with tempfile.TemporaryDirectory() as td, patch('requests.Session') as session:
            response = Mock(status_code=429)
            session.return_value.__enter__.return_value.get.return_value = response
            guard = Guard(Path(td), {'min_interval_seconds': 60, 'max_requests_per_day': 300}, 2)
            with self.assertRaises(ValueError):
                guard.get(ENDPOINT, params={'fqt': '0'})
            with self.assertRaisesRegex(ValueError, 'circuit'):
                guard.get(ENDPOINT, params={'fqt': '0'})
            self.assertEqual(session.return_value.__enter__.return_value.get.call_count, 1)
            self.assertTrue(json.loads((Path(td) / 'circuit.json').read_text())['open'])

    def test_exception_chain_and_first_circuit_cause_preserved(self):
        from http.client import RemoteDisconnected
        from urllib3.exceptions import ProtocolError
        from requests.exceptions import ConnectionError
        error = ConnectionError(ProtocolError('Connection aborted.', RemoteDisconnected('peer closed')))
        details = error_details(error)
        self.assertEqual(details['category'], 'peer_closed_without_http_response')
        self.assertIn('RemoteDisconnected', [v['type'] for v in details['exception_chain']])
        with tempfile.TemporaryDirectory() as td, patch('requests.Session') as session:
            session.return_value.__enter__.return_value.get.side_effect = error
            guard = Guard(Path(td), {'min_interval_seconds': 60, 'max_requests_per_day': 300}, 1)
            with self.assertRaises(ConnectionError):
                guard.get(ENDPOINT, params={'fqt': '0'})
            guard.block('outer_generic_failure')
            circuit=json.loads((Path(td)/'circuit.json').read_text())
            self.assertEqual(circuit['reason'], 'network_or_response_failure_requires_review')
            self.assertEqual(circuit['details']['error_details']['category'], 'peer_closed_without_http_response')
            self.assertNotIn('http_status', circuit['details'])

    def test_error_diagnostics_redact_url_and_credentials(self):
        details = error_details(ValueError('request https://host/path?token=private password=hidden api_key=secretvalue'))
        rendered=json.dumps(details)
        for secret in ['private', 'hidden', 'secretvalue', 'https://host']:
            self.assertNotIn(secret, rendered)

    def test_daily_budget_and_pacing_survive_restarts(self):
        import time
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with tempfile.TemporaryDirectory() as td, patch('requests.Session') as session, patch('time.sleep') as sleep:
            state = Path(td)
            save(state / 'pacing.json', {'day': datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(), 'count': 1, 'last_request': time.time()})
            response = Mock(status_code=200, content=b'{"rc":0,"data":{"klines":["test"]}}')
            response.json.return_value = {'rc': 0, 'data': {'klines': ['test']}}
            session.return_value.__enter__.return_value.get.return_value = response
            Guard(state, {'min_interval_seconds': 60, 'max_requests_per_day': 2}, 1).get(ENDPOINT, params={'fqt': '0'})
            self.assertGreater(sleep.call_args.args[0], 58)
            with self.assertRaisesRegex(ValueError, 'budget'):
                Guard(state, {'min_interval_seconds': 60, 'max_requests_per_day': 2}, 1).get(ENDPOINT, params={'fqt': '0'})
            self.assertEqual(session.return_value.__enter__.return_value.get.call_count, 1)

    def test_no_redirects_no_proxy_no_fallback(self):
        with tempfile.TemporaryDirectory() as td, patch('requests.Session') as session:
            response = Mock(status_code=302)
            client = session.return_value.__enter__.return_value
            client.get.return_value = response
            with self.assertRaises(ValueError):
                Guard(Path(td), {'min_interval_seconds': 60, 'max_requests_per_day': 1}, 1).get(ENDPOINT, params={'fqt': '0'})
            self.assertFalse(client.get.call_args.kwargs['allow_redirects'])
            self.assertFalse(client.trust_env)

    def test_incremental_cache_and_integrity_without_network(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        target = datetime.now(ZoneInfo('Asia/Shanghai')).date() - timedelta(days=1)
        config = {'collector': {'initial_start_date': target.isoformat(), 'request_policy': {'max_requests_per_run': 1}}}
        universe = {'symbols': ['600000'], 'as_of': '2026-08-31', 'verified_current': True}
        frame = self.frame()
        frame['日期'] = target.isoformat()
        fake = Mock()
        fake.stock_zh_a_hist.return_value = frame
        with tempfile.TemporaryDirectory() as td, patch('collectors.akshare_daily.access_gate'), patch.dict('sys.modules', {'akshare': fake}):
            state = Path(td)
            first = run(config, universe, state, True, 1)
            self.assertEqual(first['items_new'], 1)
            self.assertTrue(first['coverage_complete'])
            second = run(config, universe, state, True, 1)
            self.assertEqual(second['items_new'], 0)
            self.assertEqual(fake.stock_zh_a_hist.call_count, 1)
            (state / 'bars/600000.csv').write_text('corrupt')
            third = run(config, universe, state, True, 1)
            self.assertFalse(third['success'])
            self.assertEqual(fake.stock_zh_a_hist.call_count, 1)


if __name__ == '__main__':
    unittest.main()
