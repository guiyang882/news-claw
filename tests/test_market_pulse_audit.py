import unittest
from datetime import datetime, timezone
from workflows.market_pulse_audit import assess, COMPANIES


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
        self.news = {'events': [{'id': key, 'company': key, 'published_at': '2026-10-01T00:00:00Z'} for key in COMPANIES], 'company_briefs': {key: {'status': 'ok', 'generated_at':'2026-10-01T01:00:00Z', 'analysis': {'company':key}} for key in COMPANIES}}
        self.collections = {key: '2026-11-03T11:00:00Z' for key in COMPANIES}

    def test_no_new_disclosure_is_not_collector_failure(self):
        result = assess(self.news, self.collections, now=self.now)
        self.assertTrue(result['success'])
        self.assertEqual(len(result['companies']), 8)
        self.assertTrue(all(row['coverage'] == 'no_recent_sources' for row in result['companies']))

    def test_new_evidence_and_old_brief_require_attention(self):
        self.news['events'][0]['published_at'] = '2026-11-03T00:00:00Z'
        result = assess(self.news, self.collections, now=self.now)
        self.assertFalse(result['success'])
        self.assertIn('brief_behind_recent_sources_over_48h', result['issues'][0]['reasons'])

    def test_invalid_and_missing_collections_cannot_pass(self):
        self.news['company_briefs']['google'] = {'status': 'invalid'}
        del self.collections['nvidia']
        result = assess(self.news, self.collections, now=self.now)
        self.assertEqual({issue['company'] for issue in result['issues']}, {'google','nvidia'})

    def test_recent_brief_has_time_to_catch_up(self):
        self.news['events'][0]['published_at'] = '2026-11-03T00:00:00Z'
        self.news['company_briefs']['rocket_lab']['generated_at'] = '2026-11-02T23:00:00Z'
        self.assertTrue(assess(self.news, self.collections, now=self.now)['success'])
