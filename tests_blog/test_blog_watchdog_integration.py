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

    def run_recovery(self, reject=False, locator_failure=False, short_humanize=False, reject_repair=False, reject_once=False, brief=False):
        fixture = fixtures.DailyBlogTests()
        # Reuse the installed fixture's read-only DB backup and schema/media config.
        # All article, run and database writes are in fixture.root, a TemporaryDirectory.
        with patch.object(watch.blog, 'ROOT', Path('/mnt/quant/news-claw')):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        if brief:
            from tests_blog.test_flexible_reading import enable_brief
            enable_brief(fixture)
        saved, _ = fixture.recovery_fixture()
        if locator_failure:
            watch.blog.atomic_json(saved / 'result.json', {
                'success': False, 'error': 'Fact check locator does not exist in the evidence packet'})
            broken = watch.blog.read_json(saved / '02b-codex-correction/response.json')
            broken['article']['fact_checks'][0]['locator'] += '#invented-heading'
            watch.blog.atomic_json(saved / '02b-codex-correction/response.json', broken)
        if reject or reject_once:
            fixture.responses['review'] = lambda value: value.update(approved=False, issues=['Still unsupported'])
        if reject:
            fixture.responses['review_revised'] = lambda value: value.update(approved=False, issues=['Still unsupported'])
        if short_humanize:
            fixture.responses['humanize'] = lambda value: value['article']['en'].update(
                body_markdown=value['article']['en']['body_markdown'].replace(
                    'This synthetic example describes an offline fixture and keeps its stated evidence limits without making any real world research claim. ', 'Short fixture. '))
        if reject_repair:
            fixture.responses['review_humanize_repair'] = lambda value: value.update(approved=False, issues=['Unsupported repair'])
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
                if brief and stage == 'watchdog_repair':
                    fixture.assertIn('Target about 10 minutes per language', prompt)
                if len(self.calls) >= self.settings['network_policy']['max_cli_invocations_per_day']:
                    raise ValueError('Model invocation limit reached')
                calls.append(stage)
                self.calls.append({'stage': stage})
                value = fixture.draft() if stage in ('watchdog_repair', 'humanize_length_repair') else fixture.model(stage, prompt, schema, directory)
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
            if reject or reject_repair:
                with self.assertRaisesRegex(ValueError, 'Codex rejected'):
                    invoke()
                self.assertFalse((fixture.site / 'manifest.json').exists())
                self.assertEqual(calls, ['watchdog_repair', 'review', 'revise', 'review_revised'] if reject else
                    ['watchdog_repair', 'review', 'humanize', 'humanize_length_repair', 'review_humanize_repair'])
            else:
                result = invoke()
                self.assertEqual(result['business_status'], 'publication_verified')
                expected = ['watchdog_repair', 'review']
                if reject_once:
                    expected += ['revise', 'review_revised']
                expected += ['humanize']
                if short_humanize:
                    expected += ['humanize_length_repair', 'review_humanize_repair']
                expected += ['final_review']
                self.assertEqual(calls, expected)
                self.assertEqual(len(result['recovery']['model_calls']), 4 + len(expected))
                self.assertEqual(len(fixtures.load_runtime_articles(fixture.site)), 1)
                if brief:
                    import re
                    article = fixtures.load_runtime_articles(fixture.site)[0]
                    for label in (article['reading_time'], article['en']['reading_time']):
                        self.assertTrue(8 <= int(re.search(r'\d+', label).group()) <= 12, label)
                proof = next((fixture.site / 'automation-reviews').glob('*.json'))
                self.assertTrue(watch.blog.read_json(proof)['final_review']['approved'])
                invoke()
                self.assertEqual(len(calls), len(expected))
        self.assertFalse(watch.blog.read_json(saved / 'result.json')['success'])

    def test_full_recovery_publishes_bilingual_content_once(self):
        self.run_recovery()

    def test_brief_checkpoint_keeps_selected_length_during_watchdog_recovery(self):
        self.run_recovery(brief=True)

    def test_brief_humanizer_repair_keeps_format_and_gets_fresh_fact_review(self):
        self.run_recovery(brief=True, short_humanize=True)

    def test_rejected_independent_review_cannot_publish(self):
        self.run_recovery(reject=True)

    def test_invalid_locator_is_fixed_before_fresh_reviews_and_publication(self):
        self.run_recovery(locator_failure=True)

    def test_short_humanizer_is_repaired_then_independently_reviewed(self):
        self.run_recovery(short_humanize=True)

    def test_unsupported_post_humanizer_repair_cannot_publish(self):
        self.run_recovery(short_humanize=True, reject_repair=True)

    def test_one_factual_correction_is_reviewed_within_existing_budget(self):
        self.run_recovery(reject_once=True)
