"""Refresh slots skip completed publication without weakening collection controls."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, '/mnt/quant/strategies/stocks-quant')
from collectors import blog_evidence


class EvidenceRefreshTests(unittest.TestCase):
    def setUp(self):
        self.task = {'timezone': 'Asia/Shanghai', 'workflow': {
            'skip_when_blog_published': True,
            'website_repo': '/mnt/quant/strategies/stocks-quant', 'website_state': '/unused'}}
        self.now = datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc)

    def test_only_current_beijing_day_skips_collection(self):
        with patch('web.blog_runtime.load_runtime_articles') as load:
            load.return_value = [{'published_at': '2026-10-21'}]
            self.assertFalse(blog_evidence.publication_complete(self.task, self.now))
            load.return_value = [{'published_at': '2026-10-22'}]
            self.assertTrue(blog_evidence.publication_complete(self.task, self.now))

    def test_invalid_publication_is_not_mistaken_for_success(self):
        with patch('web.blog_runtime.load_runtime_articles', side_effect=ValueError('Invalid source hash')):
            with self.assertRaisesRegex(ValueError, 'Invalid source hash'):
                blog_evidence.publication_complete(self.task, self.now)

    def test_old_task_configuration_remains_compatible(self):
        with patch('web.blog_runtime.load_runtime_articles') as load:
            self.assertFalse(blog_evidence.publication_complete({}, self.now))
            load.assert_not_called()

    def test_refresh_configuration_keeps_existing_request_limits(self):
        task = json.loads((Path(__file__).parents[1] / 'config/tasks/daily-blog-primary-evidence.json').read_text())
        self.assertEqual(task['schedule'], '55 18 * * *')
        policy = task['collector']['request_policy']
        self.assertEqual(policy['max_requests_per_run'], 12)
        self.assertGreaterEqual(policy['min_interval_seconds_global'], 10)
        self.assertTrue(policy['stop_on_403_429_or_access_denial'])
        self.assertFalse(policy['automatic_retry_after_denial'])
        self.assertEqual(task['collector']['discovery']['max_pages_per_run'], 6)
