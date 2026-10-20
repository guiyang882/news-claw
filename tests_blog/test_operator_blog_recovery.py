import sqlite3
import unittest
from workflows.daily_blog import recoverable_run


class OperatorRecoveryTests(unittest.TestCase):
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
