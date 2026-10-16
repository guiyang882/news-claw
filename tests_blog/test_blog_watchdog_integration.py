"""Offline integration: synthetic drafts, independent verdict fixtures, temporary website."""
from datetime import datetime, timezone
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tests_blog import test_daily_blog as fixtures
from workflows import blog_watchdog as watch


class WatchdogIntegrationTests(unittest.TestCase):
    def test_codex_recovery_uses_read_only_sandbox_without_approval_escalation(self):
        fixture = fixtures.DailyBlogTests()
        with patch.object(watch.blog, 'ROOT', Path('/mnt/quant/news-claw')):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.config['workflow']['reviewer']['permissions'] = 'read-only'
        fixture.config['workflow']['writer_provider'] = 'codex'
        schema = fixture.root / 'schema.json'
        schema.write_text('{"type":"object","properties":{},"required":[]}')
        def start(command, **kwargs):
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', command)
            self.assertEqual(command[command.index('--sandbox') + 1], 'read-only')
            self.assertIn('approval_policy="never"', command)
            self.assertIn('shell_tool', command)
            self.assertIn('web_search="disabled"', command)
            self.assertEqual(command[command.index('--model') + 1], fixture.config['workflow']['reviewer']['model'])
            Path(command[command.index('--output-last-message') + 1]).write_text('{}')
            return Mock(returncode=0, poll=lambda: 0)
        with patch.object(watch.blog.subprocess, 'Popen', side_effect=start):
            runner = watch.blog.ModelRunner(fixture.config, fixture.root)
            runner('draft', 'Offline fixture', schema, fixture.directory)
            self.assertEqual(runner.calls[0]['provider'], 'codex')

    def run_recovery(self, reject=False):
        fixture = fixtures.DailyBlogTests()
        # Reuse the installed fixture's read-only DB backup and schema/media config.
        # All article, run and database writes are in fixture.root, a TemporaryDirectory.
        with patch.object(watch.blog, 'ROOT', Path('/mnt/quant/news-claw')):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        saved, _ = fixture.recovery_fixture()
        if reject:
            fixture.responses['review'] = lambda value: value.update(approved=False, issues=['Still unsupported'])
        current = 'b' * 32
        task = {'workflow': {'max_recoveries_per_day': 2, 'cooldown_seconds': 3600,
                            'max_total_model_calls_per_day': 16, 'delivery_surfaces': {'enabled': True}}}
        rows = [{'id': 'a' * 32, 'task_id': watch.WRITER_ID, 'status': 'failed',
                 'started_at': '2026-10-10T00:00:00Z', 'created_at': '2026-10-10T00:00:00Z'}]
        calls = []

        class OfflineRunner:
            def __init__(self, config, root):
                self.settings = config['workflow']
                self.calls = []
                fixture.assertEqual(self.settings['reviewer']['permissions'], 'read-only')

            def __call__(self, stage, prompt, schema, directory):
                if len(self.calls) >= self.settings['network_policy']['max_cli_invocations_per_day']:
                    raise ValueError('Model invocation limit reached')
                calls.append(stage)
                self.calls.append({'stage': stage})
                value = fixture.draft() if stage == 'watchdog_repair' else fixture.model(stage, prompt, schema, directory)
                watch.blog.atomic_json(directory / 'response.json', value)
                return value

        def inspect(*args):
            articles = fixtures.load_runtime_articles(fixture.site)
            if articles:
                return {'success': True, 'business_status': 'publication_verified'}
            return {'business_status': 'daily_publication_missing', 'readiness': {'success': True},
                    'attempt': watch.blog.read_json(fixture.root / 'data/runs/daily-blog-days/2026-10-10.json')}

        with patch.object(watch, 'read_runs', return_value=rows), \
             patch.dict(os.environ, {'NEWS_CLAW_RUN_ID': current}), \
             patch('socket.create_connection', side_effect=AssertionError('No external source/network requests')):
            invoke = lambda: watch.supervise(task, fixture.config, fixture.root, fixture.db, fixture.directory,
                execute=True, now=datetime(2026, 10, 10, 4, 15, tzinfo=timezone.utc), inspect=inspect,
                enqueue_task=Mock(side_effect=AssertionError('No enqueue during recovery')), runner_factory=OfflineRunner)
            if reject:
                with self.assertRaisesRegex(ValueError, 'Codex rejected'):
                    invoke()
                self.assertFalse((fixture.site / 'manifest.json').exists())
                self.assertEqual(calls, ['watchdog_repair', 'review'])
            else:
                result = invoke()
                self.assertEqual(result['business_status'], 'publication_verified')
                self.assertEqual(calls, ['watchdog_repair', 'review', 'humanize', 'final_review'])
                self.assertEqual(len(result['recovery']['model_calls']), 8)
                self.assertEqual(len(fixtures.load_runtime_articles(fixture.site)), 1)
                proof = next((fixture.site / 'automation-reviews').glob('*.json'))
                self.assertTrue(watch.blog.read_json(proof)['final_review']['approved'])
                invoke()
                self.assertEqual(len(calls), 4)
        self.assertFalse(watch.blog.read_json(saved / 'result.json')['success'])

    def test_full_recovery_publishes_bilingual_content_once(self):
        self.run_recovery()

    def test_rejected_independent_review_cannot_publish(self):
        self.run_recovery(reject=True)
