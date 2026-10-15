from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import pandas as pd
from collectors.csi300_membership import refresh, validate

class MembershipTest(unittest.TestCase):
    def frame(self):
        return pd.DataFrame([['20261014','000300','沪深300','CSI300',f'{i:06d}','name','name','深圳证券交易所','SZ'] for i in range(300)])

    def test_snapshot_dates_and_duplicates(self):
        frame=self.frame()
        day,symbols=validate(frame,date(2026,10,14))
        self.assertEqual(day,'2026-10-14')
        self.assertEqual(len(symbols),300)
        for target in [date(2026,10,13),date(2026,10,29)]:
            with self.assertRaisesRegex(ValueError,'stale'):
                validate(frame,target)
        frame.iloc[1,4]=frame.iloc[0,4]
        with self.assertRaisesRegex(ValueError,'symbols'):
            validate(frame,date(2026,10,14))

    def test_denial_is_not_retried(self):
        with tempfile.TemporaryDirectory() as td, patch('requests.Session') as session:
            session.return_value.__enter__.return_value.get.return_value=Mock(status_code=403)
            with self.assertRaisesRegex(ValueError,'non_200'):
                refresh(Path(td),date(2026,10,14))
            with self.assertRaisesRegex(ValueError,'circuit'):
                refresh(Path(td),date(2026,10,14))
            self.assertEqual(session.return_value.__enter__.return_value.get.call_count,1)

    def test_market_circuit_prevents_even_membership_requests(self):
        from collectors.akshare_daily import save
        with tempfile.TemporaryDirectory() as td, patch('requests.Session') as session:
            state=Path(td)
            save(state/'circuit.json', {'open': True})
            with self.assertRaisesRegex(ValueError, 'market_source_circuit'):
                refresh(state,date(2026,10,14))
            session.assert_not_called()

    def test_daily_cache_and_tamper(self):
        with tempfile.TemporaryDirectory() as td, patch('requests.Session') as session, patch('pandas.read_excel',return_value=self.frame()):
            response=Mock(status_code=200,content=b'PKfixture',headers={})
            session.return_value.__enter__.return_value.get.return_value=response
            state=Path(td)
            first=refresh(state,date(2026,10,14))
            self.assertEqual(first,refresh(state,date(2026,10,14)))
            self.assertEqual(session.return_value.__enter__.return_value.get.call_count,1)
            next((state/'membership').glob('*.xls')).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'integrity'):
                refresh(state,date(2026,10,14))
            self.assertEqual(session.return_value.__enter__.return_value.get.call_count,1)
