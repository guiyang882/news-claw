"""Offline bilingual brief publication; no model or source network access."""
from copy import deepcopy
import json
import re
import unittest

from tests_blog import test_daily_blog as fixtures
from workflows import daily_blog as blog


def enable_brief(fixture):
    fixture.config['workflow']['reading']['formats'] = [
        {'target_minutes': 20, 'tolerance_minutes': 3},
        {'target_minutes': 10, 'tolerance_minutes': 2}]
    original_plan, original_draft = fixture.plan, fixture.draft

    def plan(payload):
        value = original_plan(payload)
        value['outline']['target_reading_minutes'] = 10
        for section in value['outline']['sections']:
            section.update(zh_units_budget=500, en_words_budget=333)
        return value

    def draft():
        value = original_draft()
        for language in ('zh', 'en'):
            body = value['article'][language]['body_markdown']
            # Shorten only repeated synthetic fixture paragraphs, preserving headings/citations.
            lines = body.splitlines()
            for index, line in enumerate(lines):
                if len(line) > 500:
                    sentences = re.findall(r'.*?(?:。|\. )', line)
                    lines[index] = ''.join(sentences[:len(sentences) // 2])
            value['article'][language]['body_markdown'] = '\n'.join(lines)
        return value

    fixture.plan, fixture.draft = plan, draft


class FlexibleReadingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DailyBlogTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        enable_brief(self.fixture)

    def assert_brief(self):
        articles = fixtures.load_runtime_articles(self.fixture.site)
        self.assertEqual(len(articles), 1)
        for label in (articles[0]['reading_time'], articles[0]['en']['reading_time']):
            self.assertTrue(8 <= int(re.search(r'\d+', label).group()) <= 12, label)

    def test_brief_reaches_independent_reviews_and_bilingual_publication_once(self):
        original = self.fixture.model
        def model(stage, prompt, schema, directory):
            if stage in ('draft', 'humanize'):
                self.assertIn('Target about 10 minutes per language', prompt)
            return original(stage, prompt, schema, directory)
        self.fixture.model = model
        self.fixture.run_blog()
        self.assert_brief()
        self.assertEqual(self.fixture.calls, ['plan', 'draft', 'review', 'humanize', 'final_review'])
        formats = self.fixture.payloads['plan']['reading_formats']
        self.assertEqual([item['target_minutes'] for item in formats], [20, 10])
        self.assertEqual(formats[1]['length_requirements']['en']['minimum'], 1401)
        self.fixture.run_blog()
        self.assertEqual(len(self.fixture.calls), 5)

    def test_insufficient_evidence_still_stops_before_writing(self):
        self.fixture.responses['plan'] = lambda value: value.update(status='insufficient_evidence')
        self.assertEqual(self.fixture.run_blog()['business_status'], 'insufficient_evidence')
        self.assertEqual(self.fixture.calls, ['plan'])
        self.assertFalse(fixtures.load_runtime_articles(self.fixture.site))

    def test_brief_rejected_review_cannot_publish(self):
        for stage in ('review', 'review_revised'):
            self.fixture.responses[stage] = lambda value: value.update(approved=False, issues=['Unsupported claim'])
        with self.assertRaisesRegex(ValueError, 'Codex rejected'):
            self.fixture.run_blog()
        self.assertFalse(fixtures.load_runtime_articles(self.fixture.site))

    def test_unapproved_reading_target_stops_before_writer(self):
        self.fixture.responses['plan'] = lambda value: value['outline'].update(target_reading_minutes=5)
        with self.assertRaisesRegex(ValueError, 'allowed reading format'):
            self.fixture.run_blog()
        self.assertEqual(self.fixture.calls, ['plan'])

    def test_brief_still_requires_two_distinct_evidence_urls(self):
        self.fixture.pulses['sources'][1]['url'] = self.fixture.pulses['sources'][0]['url']
        (self.fixture.root / 'company_pulses.json').write_text(json.dumps(self.fixture.pulses))
        self.assertEqual(self.fixture.run_blog()['business_status'], 'insufficient_evidence')
        self.assertEqual(self.fixture.calls, [])
        self.assertFalse(fixtures.load_runtime_articles(self.fixture.site))

    def test_legacy_long_only_config_does_not_silently_accept_short_articles(self):
        self.fixture.config['workflow']['reading'].pop('formats')
        with self.assertRaisesRegex(ValueError, 'allowed reading format'):
            self.fixture.run_blog()

    def test_short_format_cannot_keep_long_outline_budgets(self):
        def inflate(value):
            for section in value['outline']['sections']:
                section.update(zh_units_budget=1000, en_words_budget=667)
        self.fixture.responses['plan'] = inflate
        with self.assertRaisesRegex(ValueError, 'length budget'):
            self.fixture.run_blog()

    def test_brief_repair_uses_selected_budget_and_requires_fresh_reviews(self):
        self.fixture.responses['draft'] = lambda value: value['article']['en'].update(
            body_markdown='# Short\n' + '\n## Section\nText.' * 6 +
            '\n[First](https://example.org/a) [Second](https://example.org/b)')
        self.fixture.run_blog()
        self.assert_brief()
        payload = self.fixture.payloads['repair_length']
        self.assertEqual(payload['measured_lengths']['en']['minimum'], 1401)
        self.assertEqual(self.fixture.calls, ['plan', 'draft', 'repair_length', 'review', 'humanize', 'final_review'])

    def test_reading_formats_are_validated_without_mutating_policy(self):
        policy = self.fixture.config['workflow']['reading']
        before = deepcopy(policy)
        chosen = blog.editorial.reading_for_plan({'reading': policy}, {'outline': {'target_reading_minutes': 10}})
        self.assertEqual(chosen['target_minutes'], 10)
        self.assertEqual(policy, before)
        for invalid in ({'target_minutes': 10, 'tolerance_minutes': 10},
                        {'target_minutes': True, 'tolerance_minutes': 0}):
            bad = deepcopy(policy)
            bad['formats'].append(invalid)
            with self.assertRaises(ValueError):
                blog.editorial.reading_options(bad)
