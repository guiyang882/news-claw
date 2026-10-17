from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from workflows import blog_watchdog as watch


NOW = datetime(2026, 10, 16, 4, 15, tzinfo=timezone.utc)
PRIOR = 'a' * 32
CURRENT = 'b' * 32


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / 'test.sqlite3'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE task_runs(id TEXT,task_id TEXT,status TEXT,started_at TEXT,created_at TEXT)')
        self.directory = self.root / 'data/runs' / CURRENT
        self.directory.mkdir(parents=True)
        self.saved = self.root / 'data/runs' / PRIOR
        self.task = {'workflow': {'delivery_surfaces': {'enabled': True}, 'max_recoveries_per_day': 2,
                                 'cooldown_seconds': 3600, 'max_total_model_calls_per_day': 16}}
        self.writer = {'timezone': 'Asia/Shanghai', 'execution': {'timeout_seconds': 4500}, 'workflow': {
            'network_policy': {'max_cli_invocations_per_day': 10}, 'max_draft_revisions': 1}}
        self.missing = {'business_status': 'daily_publication_missing', 'attempt': None,
                        'readiness': {'success': True}}
        self.healthy = {'success': True, 'business_status': 'publication_verified', 'needs_attention': False}
        self.inspect = Mock(return_value=self.missing)
        self.enqueue = Mock(return_value='c' * 32)
        self.factory = Mock(side_effect=AssertionError('models must not be called'))
        self.publish = Mock(side_effect=AssertionError('must not publish'))
        environment = patch.dict(os.environ, {'NEWS_CLAW_RUN_ID': CURRENT})
        environment.start()
        self.addCleanup(environment.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def add_run(self, run_id=PRIOR, task=watch.WRITER_ID, status='failed', stamp='2026-10-15T23:30:00Z'):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO task_runs VALUES (?,?,?,?,?)', (run_id, task, status, stamp, stamp))

    def failed(self, error='Codex rejected the article; publication stopped'):
        self.add_run()
        self.write(self.saved / 'result.json', {'error': error})
        self.write(self.saved / '01-agy-draft/response.json', {'status': 'ready', 'article': {'tags': ['test']}})
        self.write(self.saved / 'source-packet.json', {'day': '2026-10-16', 'sources': [], 'evidence': []})
        self.write(self.saved / 'blog-outline.json', {'plan': 'saved'})
        self.write(self.saved / '02-codex-review/response.json', {'approved': False, 'issues': ['Fix maturity language']})
        self.missing['attempt'] = {'status': 'failed', 'run_id': PRIOR}

    def invoke(self, execute=False):
        return watch.supervise(self.task, self.writer, self.root, self.db, self.directory,
            execute=execute, now=NOW, inspect=self.inspect, enqueue_task=self.enqueue,
            runner_factory=self.factory, publish_workflow=self.publish)

    def test_published_article_is_verified_without_models_or_state_writes(self):
        self.inspect.return_value = self.healthy
        self.assertEqual(self.invoke(True), self.healthy)
        self.factory.assert_not_called()
        self.enqueue.assert_not_called()
        self.assertFalse((self.root / 'data/runs/blog-watchdog-days').exists())

    def test_surface_failure_never_rewrites_published_content(self):
        self.inspect.return_value = {'success': False, 'business_status': 'publication_surface_mismatch'}
        self.assertEqual(self.invoke(True)['business_status'], 'publication_surface_mismatch')
        self.publish.assert_not_called()

    def test_running_and_queued_work_are_not_duplicated_or_killed(self):
        self.add_run(status='running', stamp='2026-10-16T04:00:00Z')
        self.assertEqual(self.invoke(True)['business_status'], 'task_in_progress')
        self.enqueue.assert_not_called()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE task_runs SET status='queued'")
        self.assertEqual(self.invoke(True)['business_status'], 'task_in_progress')

    def test_stalled_process_reports_attention_without_mutation(self):
        self.add_run(status='running')
        result = self.invoke(True)
        self.assertEqual(result['business_status'], 'task_stalled')
        self.assertTrue(result['needs_attention'])
        self.enqueue.assert_not_called()

    def test_preview_does_not_enqueue_or_reserve(self):
        self.assertEqual(self.invoke()['business_status'], 'would_enqueue')
        self.enqueue.assert_not_called()
        self.assertFalse((self.root / 'data/runs/blog-watchdog-days').exists())

    def test_missing_writer_is_enqueued_only_once_even_after_uncertain_enqueue(self):
        self.enqueue.side_effect = RuntimeError('uncertain enqueue')
        with self.assertRaises(RuntimeError):
            self.invoke(True)
        self.assertEqual(self.invoke(True)['business_status'], 'restart_already_requested')
        self.assertEqual(self.enqueue.call_count, 1)

    def test_missing_upstream_can_start_once_but_failed_or_denied_cannot(self):
        self.missing['readiness'] = {'success': False, 'upstream': {'reason': 'upstream_not_run_today'}}
        self.assertEqual(self.invoke(True)['task_id'], watch.EVIDENCE_ID)
        self.enqueue.assert_called_once_with(self.root, watch.EVIDENCE_ID)
        self.missing['readiness']['upstream']['reason'] = 'upstream_not_successful'
        self.assertEqual(self.invoke(True)['business_status'], 'evidence_needs_attention')
        self.assertEqual(self.enqueue.call_count, 1)

    def test_provider_denial_is_not_reset(self):
        path = self.root / 'data/runs/blog-provider-policy/codex.blocked.json'
        self.write(path, {'reason': 'denied'})
        self.assertEqual(self.invoke(True)['business_status'], 'provider_circuit_open')
        self.assertEqual(json.loads(path.read_text()), {'reason': 'denied'})
        self.factory.assert_not_called()

    def test_repair_preview_and_daily_limit(self):
        self.failed()
        self.assertEqual(self.invoke()['business_status'], 'would_repair')
        self.write(self.root / 'data/runs/blog-watchdog-days/2026-10-16.json',
                   {'attempts': [{}, {}], 'enqueued': []})
        self.assertEqual(self.invoke(True)['business_status'], 'daily_recovery_limit')

    def test_invalid_evidence_locator_is_recoverable_content(self):
        self.failed('Fact check locator does not exist in the evidence packet')
        self.assertEqual(self.invoke()['business_status'], 'would_repair')
        self.factory.assert_not_called()

    def test_draft_schema_limits_locators_to_exact_selected_evidence(self):
        packet = {'evidence': [
            {'source_ids': ['chosen'], 'locator': 'data/chosen.json'},
            {'source_ids': ['other'], 'locator': 'data/other.json'}]}
        with patch.object(watch.blog.editorial, 'selected_candidate', return_value={'source_ids': ['chosen']}):
            path = watch.blog.draft_schema({}, self.root / 'schema.json', packet=packet)
        locator = json.loads(path.read_text())['properties']['article']['properties']['fact_checks']['items']['properties']['locator']
        self.assertEqual(locator['enum'], ['data/chosen.json'])
        watch.blog.validate_shape('data/chosen.json', locator)
        for bad in ('data/other.json', 'data/chosen.json — Chapter title', 'data/chosen.json#section'):
            with self.subTest(locator=bad), self.assertRaises(ValueError):
                watch.blog.validate_shape(bad, locator)

    def test_cooldown_prevents_immediate_retry(self):
        self.failed()
        self.write(self.root / 'data/runs/blog-watchdog-days/2026-10-16.json',
                   {'attempts': [{'started_at': '2026-10-16T04:00:00Z'}], 'enqueued': []})
        self.assertEqual(self.invoke(True)['business_status'], 'recovery_cooldown')

    def test_unrelated_attempts_count_toward_total_budget(self):
        self.failed()
        other = 'd' * 32
        self.add_run(run_id=other, task=watch.TASK_ID)
        for i in range(12):
            self.write(self.root / 'data/runs' / other / str(i) / 'call.json', {})
        result = self.invoke(True)
        self.assertEqual(result['business_status'], 'daily_model_budget_exhausted')
        self.assertEqual(result['calls_used'], 14)
        self.factory.assert_not_called()

    def test_replay_artifacts_are_not_billed_twice(self):
        self.add_run()
        self.write(self.saved / 'plan/response.json', {})
        self.write(self.saved / 'plan/reused-stage.json', {})
        self.write(self.saved / 'review/call.json', {})
        self.write(self.saved / 'review/response.json', {})
        calls = watch.daily_calls(self.root, watch.read_runs(self.db), NOW.date(), ZoneInfo('Asia/Shanghai'))
        self.assertEqual(len(calls), 1)

    def test_unrecoverable_infrastructure_error_is_not_given_to_codex(self):
        self.failed('Permission denied writing manifest')
        self.assertEqual(self.invoke(True)['business_status'], 'failure_outside_content_recovery')
        self.factory.assert_not_called()

    def test_new_evidence_required_before_replanning(self):
        self.failed()
        self.missing['attempt']['status'] = 'insufficient_evidence'
        with patch.object(watch.blog, 'collect_packet', return_value={'sources': [], 'evidence': [], 'approved_media': []}) as collect:
            self.assertEqual(self.invoke(True)['business_status'], 'awaiting_new_verified_evidence')
            collect.return_value = {'sources': [{'id': 'new'}], 'evidence': []}
            self.assertEqual(self.invoke()['business_status'], 'would_replan')

    def test_repair_uses_reviews_budget_and_post_publication_verification(self):
        self.failed()
        original_writer = deepcopy(self.writer)
        corrected = {'status': 'ready', 'article': {'tags': ['test']}}
        runner = Mock(return_value=corrected)
        runner.calls = []
        self.factory.side_effect = None
        self.factory.return_value = runner
        self.publish.side_effect = None
        self.publish.return_value = {'success': True, 'business_status': 'published'}
        self.inspect.side_effect = [self.missing, self.healthy]
        with patch.object(watch.blog, 'draft_schema', return_value=self.root / 'schema.json'), \
             patch.object(watch.blog, 'selected_packet', return_value={'sources': []}), \
             patch.object(watch.blog, 'length_prompt', return_value=''), \
             patch.object(watch.blog.presentation, 'writing_guidance', return_value=''), \
             patch.object(watch.blog, 'build_draft'):
            result = self.invoke(True)
        self.assertEqual(result['business_status'], 'publication_verified')
        self.assertTrue(result['watchdog_recovered'])
        runner.assert_called_once()
        self.assertIn('Fix maturity language', runner.call_args.args[1])
        passed = self.publish.call_args.args[0]['workflow']
        self.assertEqual(passed['manual_recovery']['run_id'], PRIOR)
        self.assertEqual(passed['network_policy']['max_cli_invocations_per_day'], 16)
        self.assertEqual(passed['max_draft_revisions'], 0)
        self.assertEqual(self.writer, original_writer)
        self.assertEqual(self.inspect.call_count, 2)

    def test_model_failure_reserves_attempt_before_any_model_work(self):
        self.failed()
        with patch.object(watch.blog, 'draft_schema'), patch.object(watch.blog, 'length_prompt', return_value=''), \
             patch.object(watch.blog.presentation, 'writing_guidance', return_value=''), \
             patch.object(watch.blog, 'selected_packet', return_value={}):
            with self.assertRaises(AssertionError):
                self.invoke(True)
        state = json.loads((self.root / 'data/runs/blog-watchdog-days/2026-10-16.json').read_text())
        self.assertEqual(len(state['attempts']), 1)
        self.assertEqual(state['attempts'][0]['run_id'], CURRENT)
