import sqlite3
import unittest
from workflows.daily_blog import recoverable_run, replannable_run, has_new_evidence


class OperatorRecoveryTests(unittest.TestCase):
    def test_replan_accepts_only_terminal_insufficient_evidence_blog_checkpoints(self):
        import json
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE task_runs(id TEXT,task_id TEXT,status TEXT,metadata_json TEXT)')
            for task in ('daily-blog-agy-codex', 'daily-blog-watchdog', 'unrelated-task'):
                for status in ('failed', 'succeeded', 'running', 'queued'):
                    for result in ('insufficient_evidence', 'published', 'failed'):
                        key = task + status + result
                        db.execute('INSERT INTO task_runs VALUES (?,?,?,?)', (key, task, status, json.dumps({'result': {'business_status': result}})))
                        self.assertEqual(replannable_run(db, key, 'daily-blog-agy-codex'),
                                         task != 'unrelated-task' and status in ('failed', 'succeeded') and result == 'insufficient_evidence')
            self.assertFalse(replannable_run(db, 'missing', 'daily-blog-agy-codex'))

    def test_replan_ignores_headlines_metadata_order_and_removed_sources(self):
        from copy import deepcopy
        old = {'sources': [{'id': 'body', 'url': 'https://example.org/body', 'evidence_level': 'cached_webpage'}],
               'evidence': [{'source_ids': ['body'], 'record_type': 'webpage', 'text': 'A complete source body', 'fetched_at': '2026-10-20', 'locator': 'old.json'}]}
        fresh = deepcopy(old)
        fresh['evidence'][0].update(fetched_at='2026-10-21', locator='new.json', text='A  complete\nsource body')
        fresh['sources'].append({'id': 'headline', 'url': 'https://example.org/news', 'evidence_level': 'headline_discovery'})
        fresh['evidence'].append({'source_ids': ['headline'], 'text': 'A new RSS headline', 'record_type': 'feed_entry'})
        self.assertFalse(has_new_evidence(old, fresh))
        self.assertFalse(has_new_evidence(old, {'sources': [], 'evidence': []}))
        fresh['evidence'].reverse()
        self.assertFalse(has_new_evidence(old, fresh))
        fresh['evidence'][-1]['text'] += ' with a new disclosed result'
        self.assertTrue(has_new_evidence(old, fresh))

    def test_only_failed_blog_checkpoints_can_be_recovered_by_writer(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE task_runs(id TEXT,task_id TEXT,status TEXT)')
            for task in ('daily-blog-agy-codex', 'daily-blog-watchdog', 'unrelated-task'):
                for status in ('failed', 'running', 'succeeded', 'queued'):
                    key = task + status
                    db.execute('INSERT INTO task_runs VALUES (?,?,?)', (key, task, status))
                    self.assertEqual(recoverable_run(db, key, 'daily-blog-agy-codex'),
                                     task != 'unrelated-task' and status == 'failed')
            self.assertFalse(recoverable_run(db, 'daily-blog-watchdogfailed', 'unrelated-task'))
            self.assertFalse(recoverable_run(db, 'missing', 'daily-blog-agy-codex'))

    def test_complete_pre_review_budget_checkpoint_still_requires_all_reviews(self):
        from pathlib import Path
        from unittest.mock import patch
        from tests_blog import test_daily_blog as fixtures
        from workflows import daily_blog as blog
        fixture=fixtures.DailyBlogTests()
        with patch.object(blog,'ROOT',Path('/mnt/quant/news-claw')):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        saved, runner=fixture.recovery_fixture()
        packet=blog.read_json(saved/'source-packet.json')
        plan=blog.read_json(saved/'blog-outline.json')
        blog.atomic_json(saved/'original-draft.json',blog.build_draft(fixture.draft(),packet,fixture.config,fixtures.DAY,plan=plan))
        blog.atomic_json(saved/'result.json',{'success':False,'error':'Model invocation limit reached'})
        result=blog.run(fixture.config,fixture.root,fixture.db,fixture.directory,execute=True,model_runner=runner,day=fixtures.DAY)
        self.assertEqual(result['business_status'],'published')
        self.assertEqual(fixture.calls,['review','humanize','final_review'])

    def test_metadata_failure_recovery_keeps_fresh_reviews_and_matching_site_limits(self):
        from pathlib import Path
        from unittest.mock import patch
        from tests_blog import test_daily_blog as fixtures
        from workflows import daily_blog as blog
        from web.blog_runtime import ARTICLE_METADATA_LIMITS
        self.assertEqual(blog.ARTICLE_METADATA_LIMITS, ARTICLE_METADATA_LIMITS)
        fixture = fixtures.DailyBlogTests()
        with patch.object(blog, 'ROOT', Path('/mnt/quant/news-claw')):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        saved, runner = fixture.recovery_fixture()
        blog.atomic_json(saved/'result.json', {'success':False, 'error':'Article metadata exceeds website limits'})
        result = blog.run(fixture.config,fixture.root,fixture.db,fixture.directory,execute=True,model_runner=runner,day=fixtures.DAY)
        self.assertEqual(result['business_status'], 'published')
        self.assertEqual(fixture.calls, ['review','humanize','final_review'])
        guidance = blog.length_prompt(fixture.config['workflow'])
        self.assertIn('summary <= 1200', guidance)
        self.assertIn('home_note <= 600', guidance)
        self.assertIn('INCLUDING Markdown and URLs', guidance)
