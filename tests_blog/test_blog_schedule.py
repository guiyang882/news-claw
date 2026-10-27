"""Publication cadence, no off-day side effects, and edition evidence boundaries."""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from workflows import blog_schedule as schedule, daily_blog as blog, blog_delivery as delivery, blog_watchdog as watchdog

ROOT = Path(__file__).resolve().parents[1]


class BlogScheduleTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'config/tasks/daily-blog-agy-codex.json').read_text())

    def test_only_friday_and_sunday_across_month_boundary(self):
        days = [date(2026, 10, n) for n in range(27, 32)] + [date(2026, 11, n) for n in range(1, 7)]
        for day in days:
            with self.subTest(day=day):
                self.assertEqual(schedule.off_day(self.config, day) is None, day.isoweekday() in (5, 7))
        self.assertEqual(schedule.off_day(self.config, date(2026, 10, 31))['next_publication_day'], '2026-11-01')
        friday = schedule.edition(self.config, date(2026, 10, 30))
        sunday = schedule.edition(self.config, date(2026, 11, 1))
        self.assertEqual((friday['window_start'], friday['window_end']), ('2026-10-26', '2026-10-30'))
        self.assertEqual((sunday['window_start'], sunday['window_end']), ('2026-10-31', '2026-11-01'))
        self.assertEqual(sunday['source_window_start'], '2026-10-26')

    def test_historical_runs_and_unconfigured_tasks_keep_existing_behavior(self):
        self.assertIsNone(schedule.off_day(self.config, date(2026, 10, 22)))
        self.assertIsNone(schedule.edition(self.config, date(2026, 10, 23)))
        self.assertIsNone(schedule.off_day({'workflow': {}}, date(2026, 10, 28)))

    def test_off_day_writer_and_checks_do_not_read_or_reserve_anything(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runner = Mock(side_effect=AssertionError('No models'))
            with patch.object(blog, 'collect_packet', side_effect=AssertionError('No packet')):
                result = blog.run(self.config, root, root/'missing.db', root/'run', execute=True,
                                  model_runner=runner, day=date(2026, 10, 28))
                for check in (delivery.preflight, delivery.inspect_delivery):
                    self.assertEqual(check(self.config, root, root/'missing.db', date(2026, 10, 28)), result)
            self.assertTrue(result['success'])
            self.assertFalse(result['needs_attention'])
            self.assertEqual(result['business_status'], 'not_publication_day')
            runner.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_watchdog_uses_beijing_day_before_inspection_or_enqueue(self):
        fail = Mock(side_effect=AssertionError('No side effects'))
        # UTC Thursday 16:30 is Friday in Beijing; Thursday 15:30 is still off-day.
        task = {'workflow': {'delivery_surfaces': {}}}
        for now, expected in [(datetime(2026, 10, 29, 15, 30, tzinfo=timezone.utc), 'not_publication_day'),
                              (datetime(2026, 10, 29, 16, 30, tzinfo=timezone.utc), 'publication_verified')]:
            inspect = Mock(return_value={'success': True, 'business_status': 'publication_verified'})
            result = watchdog.supervise(task, self.config, Path('/unused'), Path('/unused'), Path('/unused'),
                                        execute=True, now=now, inspect=inspect, enqueue_task=fail,
                                        runner_factory=fail, publish_workflow=fail)
            self.assertEqual(result['business_status'], expected)
            self.assertEqual(inspect.call_count, int(expected == 'publication_verified'))
        fail.assert_not_called()

    def packet(self):
        return {'edition': schedule.edition(self.config, date(2026, 11, 1)),
                'sources': [{'id': name, 'url': f'https://example.org/{name}', 'source_date': stamp,
                             'evidence_level': 'cached_webpage'} for name, stamp in
                            [('weekend', '2026-10-30T17:00:00Z'), ('background', '2026-10-21'), ('future', '2026-11-02')]],
                'evidence': [{'source_ids': [name], 'record_type': 'webpage', 'text': 'e' * 1100}
                             for name in ('weekend', 'background', 'future')]}

    def test_source_date_not_fetch_time_and_real_full_body_define_current_edition(self):
        packet = self.packet()
        self.assertEqual(schedule.period_source_ids(packet), {'weekend'})
        packet['evidence'][0].update(record_type='feed_entry', fetched_at='2026-11-01')
        self.assertEqual(schedule.period_source_ids(packet), set())

    def test_readiness_needs_unused_this_week_body_not_only_old_valid_sources(self):
        packet = self.packet()
        # Use a plain local Saturday date here; timestamp conversion is tested above.
        packet['sources'][0]['source_date'] = '2026-10-31'
        settings = self.config['workflow']['readiness']
        self.assertTrue(delivery.assess_packet(packet, [], settings, date(2026, 11, 1))['ready'])
        # An unused weekday source may support a clearly dated Sunday feature.
        packet['sources'][0]['source_date'] = '2026-10-29'
        self.assertTrue(delivery.assess_packet(packet, [], settings, date(2026, 11, 1))['ready'])
        packet['sources'][0]['source_date'] = '2026-10-23'
        result = delivery.assess_packet(packet, [], settings, date(2026, 11, 1))
        self.assertIn('no_unused_full_body_in_edition_window', result['reasons'])
        packet['sources'][0]['source_date'] = '2026-10-31'
        used = [{'published_at': '2026-10-31', 'sources': [packet['sources'][0]]}]
        self.assertIn('no_unused_full_body_in_edition_window', delivery.assess_packet(packet, used, settings, date(2026, 11, 1))['reasons'])

    def test_outline_must_actually_cite_current_edition_source(self):
        packet = self.packet()
        plan = {'status': 'ready', 'selected_candidate_id': 'topic',
                'candidates': [{'id': 'topic', 'source_ids': ['weekend', 'background']}],
                'outline': {'sections': [{'evidence_refs': [{'source_id': 'weekend'}]}]}}
        schedule.validate_edition_plan(plan, packet)
        plan['outline']['sections'][0]['evidence_refs'][0]['source_id'] = 'background'
        with self.assertRaisesRegex(ValueError, 'coverage window'):
            schedule.validate_edition_plan(plan, packet)

    def test_packet_and_planner_carry_edition_focus(self):
        with tempfile.TemporaryDirectory() as folder:
            import sqlite3
            root = Path(folder)
            db = root / 'cache.db'
            with sqlite3.connect(db) as connection:
                connection.execute('CREATE TABLE documents(id,canonical_url,title,published_at,fetched_at,source_json,topic_links_json)')
            config = deepcopy(self.config)
            config['workflow']['inputs'].update(company_pulses=str(root/'none'), news_timeline=str(root/'none'), max_reviewed_topic_summaries=0)
            packet = blog.collect_packet(config, root, db, date(2026, 10, 30), include_media=False)
            self.assertEqual(packet['edition']['window_start'], '2026-10-26')
            prompt = blog.planning_prompt(packet, [], config['workflow'], '')
            self.assertIn('friday-week-review', prompt)
            self.assertIn('周日聚焦周末', prompt)


if __name__ == '__main__':
    unittest.main()
