"""Offline workflow tests with fake model responses and the real website renderer."""

from copy import deepcopy
from contextlib import closing
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from workflows import daily_blog as blog


DAY = date(2026, 10, 10)
SITE_REPO = "/mnt/quant/strategies/stocks-quant"
sys.path.insert(0, SITE_REPO)
from web.blog_runtime import load_runtime_articles


class DailyBlogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.site = self.root / "site"
        self.site.mkdir()
        self.directory = self.root / "run"
        self.db = self.root / "news.sqlite3"
        with closing(sqlite3.connect(blog.ROOT / "data/db/news.sqlite3")) as original, closing(sqlite3.connect(self.db)) as copy:
            original.backup(copy)
        self.config = json.loads((blog.ROOT / "config/tasks/daily-blog-agy-codex.json").read_text())
        self.config["workflow"]["website_state"] = str(self.site)
        self.config["workflow"]["min_model_interval_seconds"] = 0
        inputs = self.config["workflow"]["inputs"]
        inputs["company_pulses"] = str(self.root / "company_pulses.json")
        inputs["news_timeline"] = str(self.root / "no-timeline.json")
        sources = [{"id": f"source-{name}", "url": f"https://example.org/{name}", "publisher": "Test issuer",
                    "source_date": "2026-10-09", "title": "Synthetic disclosure"} for name in ("a", "b")]
        self.pulses = {"as_of": "2026-10-09", "sources": sources,
                       "companies": {"test": {"disclaimer": "Synthetic data for offline testing, not real market evidence.",
                           "metrics": [{"source_ids": [source["id"]], "label": "Synthetic metric", "value": "Test value"} for source in sources]}}}
        (self.root / "company_pulses.json").write_text(json.dumps(self.pulses))
        self.calls = []
        self.responses = {}

    def draft(self):
        article = {"tags": ["primary-sources"], "used_source_ids": ["source-a", "source-b"],
            "fact_checks": [{"source_id": f"source-{name}", "claim": "This synthetic claim exists only in an offline fixture.",
                "boundary": "No part of the test fixture is verified real-world evidence.",
                "locator": f"company_pulses.json/companies/test/metrics/{index}"} for index, name in enumerate(("a", "b"))]}
        for language in ("zh", "en"):
            article[language] = {"title": "离线测试文章" if language == "zh" else "An offline test article",
                "summary": "Synthetic fixture, not a real research claim.", "home_note": "An offline fixture.",
                "category": "Research", "keywords": ["fixture"], "reading_time": "5 min read",
                "body_markdown": "# Offline fixture\n\n" + "".join(f"\n## Section {i}\n" +
                    "This is synthetic test evidence, with a source and a stated boundary. " * 12 for i in range(3)) +
                    "\n[First source](https://example.org/a) [Second source](https://example.org/b)\n"}
        return {"status": "ready", "reason": "Local fixture only.", "article": article}

    def model(self, stage, prompt, schema, directory):
        self.calls.append(stage)
        if stage in ("draft", "revise"):
            value = self.draft()
        elif stage == "humanize":
            self.assertIn("HUMANIZER_SKILL", prompt)
            self.assertIn("name: humanizer", prompt)
            value = self.draft()
            for language in ("zh", "en"):
                value["article"][language]["body_markdown"] = value["article"][language]["body_markdown"].replace("with a source and a stated boundary", "with explicit sources and limits")
        else:
            payload = json.loads(prompt.split("INPUT_DATA_JSON\n", 1)[1])
            value = {"approved": True, "facts_supported": True, "languages_consistent": True, "citations_valid": True,
                "humanizer_applied": stage == "final_review", "article_sha256": payload["article_sha256"],
                "packet_sha256": payload["packet_sha256"], "issues": [], "reason": "Offline fixture passed."}
        if stage in self.responses:
            self.responses[stage](value)
        blog.validate_shape(value, json.loads(schema.read_text()))
        return value

    def run_blog(self, execute=True):
        with patch("socket.create_connection", side_effect=AssertionError("No source network requests allowed")):
            return blog.run(self.config, self.root, self.db, self.directory, execute=execute, model_runner=self.model, day=DAY)

    def test_preview_never_calls_models_or_publishes(self):
        result = self.run_blog(False)
        self.assertEqual(result["business_status"], "preview")
        self.assertEqual(self.calls, [])
        self.assertFalse((self.site / "manifest.json").exists())

    def test_all_four_stages_publish_both_languages_once_and_render(self):
        result = self.run_blog()
        self.assertEqual(self.calls, ["draft", "review", "humanize", "final_review"])
        self.assertEqual(result["business_status"], "published")
        self.assertNotIn("knowledge_index_error", result)
        articles = load_runtime_articles(self.site)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["automation"]["approval_kind"], "model_review")
        self.assertFalse((self.site / "approvals").exists())
        proof = json.loads((self.site / "automation-reviews/daily-research-2026-10-10.json").read_text())
        self.assertEqual(proof["final_review"]["article_sha256"], blog.digest(proof["draft"]))
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertIsNotNone(connection.execute("SELECT 1 FROM artifacts WHERE id='daily-blog-2026-10-10'").fetchone())
        with patch.dict(os.environ, {"QUANT_BLOG_RUNTIME_DIR": str(self.site)}):
            from web.app import create_app
            report = self.root / "report.json"
            report.write_text(json.dumps({"schema_version": 1, "strategies": []}))
            app = create_app(report, self.root / "stats.sqlite3", self.root / "feedback.sqlite3")
            client = app.test_client()
            for path in ("/blog/daily-research-2026-10-10", "/blog/daily-research-2026-10-10?lang=en",
                         "/blog/daily-research-2026-10-10.md", "/blog", "/blog/feed.xml", "/blog-sitemap.xml"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn(b"daily-research-2026-10-10" if path.endswith("xml") else b"Offline" if ".md" in path else b"", response.data)
        count = len(self.calls)
        self.assertEqual(self.run_blog()["business_status"], "already_published")
        self.assertEqual(len(self.calls), count)

    def test_initial_review_rejection_prevents_editing_and_publication(self):
        self.config["workflow"]["max_draft_revisions"] = 0
        self.responses["review"] = lambda value: value.update(approved=False, issues=["Unsupported claim"])
        with self.assertRaisesRegex(ValueError, "rejected"):
            self.run_blog()
        self.assertEqual(self.calls, ["draft", "review"])
        self.assertFalse((self.site / "manifest.json").exists())
        self.assertEqual(self.run_blog()["business_status"], "previous_attempt_failed")
        self.assertEqual(len(self.calls), 2)

    def test_one_factual_correction_must_pass_a_new_review_before_humanizer(self):
        self.responses["review"] = lambda value: value.update(approved=False, issues=["Correct the claim"])
        self.responses["revise"] = lambda value: value["article"].update(tags=["invented-editor-tag"])
        result = self.run_blog()
        self.assertEqual(result["business_status"], "published")
        self.assertEqual(self.calls, ["draft", "review", "revise", "review_revised", "humanize", "final_review"])
        proof = json.loads((self.site / "automation-reviews/daily-research-2026-10-10.json").read_text())
        self.assertTrue(proof["initial_review"]["approved"])
        self.assertEqual(proof["initial_review"]["article_sha256"], blog.digest(proof["original_draft"]))
        self.assertEqual(proof["draft"]["article"]["tags"], self.draft()["article"]["tags"])

    def test_correction_rejected_again_stops_without_further_attempts(self):
        reject = lambda value: value.update(approved=False, issues=["Still unsupported"])
        self.responses.update(review=reject, review_revised=reject)
        with self.assertRaisesRegex(ValueError, "rejected"):
            self.run_blog()
        self.assertEqual(self.calls, ["draft", "review", "revise", "review_revised"])
        self.assertFalse((self.site / "manifest.json").exists())

    def test_insufficient_evidence_response_can_have_empty_facts(self):
        def insufficient(value):
            value["status"] = "insufficient_evidence"
            value["article"]["used_source_ids"] = []
            value["article"]["fact_checks"] = []
            for language in ("zh", "en"):
                value["article"][language]["body_markdown"] = ""
                value["article"][language]["keywords"] = []
        self.responses["draft"] = insufficient
        result = self.run_blog()
        self.assertEqual(result["business_status"], "insufficient_evidence")
        self.assertEqual(self.calls, ["draft"])
        self.assertFalse((self.site / "manifest.json").exists())

    def test_final_review_must_confirm_humanizer_work(self):
        self.responses["final_review"] = lambda value: value.update(humanizer_applied=False)
        with self.assertRaisesRegex(ValueError, "humanizer"):
            self.run_blog()
        self.assertFalse((self.site / "manifest.json").exists())

    def test_humanizer_cannot_change_fact_metadata(self):
        self.responses["humanize"] = lambda value: value["article"]["fact_checks"][0].update(claim="An altered and unsupported fabricated fact.")
        with self.assertRaisesRegex(ValueError, "Humanizer changed"):
            self.run_blog()
        self.assertFalse((self.site / "manifest.json").exists())
        self.assertEqual(self.calls, ["draft", "review", "humanize"])

    def test_final_hash_mismatch_and_rejection_prevent_publication(self):
        self.responses["final_review"] = lambda value: value.update(article_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "exact article"):
            self.run_blog()
        self.assertFalse((self.site / "manifest.json").exists())

    def test_unknown_citation_or_locator_is_rejected(self):
        def invented(value):
            value["article"]["zh"]["body_markdown"] += " [Invented](https://example.org/invented)"
        self.responses["draft"] = invented
        with self.assertRaisesRegex(ValueError, "invented a citation"):
            self.run_blog()
        self.assertEqual(self.calls, ["draft"])

    def test_stale_snapshot_or_single_source_never_calls_models(self):
        self.pulses["as_of"] = "2026-01-01"
        (self.root / "company_pulses.json").write_text(json.dumps(self.pulses))
        self.assertEqual(self.run_blog()["business_status"], "insufficient_evidence")
        self.assertEqual(self.calls, [])

    def test_provider_denial_is_persistent_and_no_second_call_occurs(self):
        runner = blog.ModelRunner(self.config, self.root)
        blocked = self.root / "data/runs/blog-provider-policy/agy.blocked.json"
        blog.atomic_json(blocked, {"reason": "Provider denied access"})
        with patch("subprocess.Popen", side_effect=AssertionError("Blocked provider cannot be called")):
            with self.assertRaisesRegex(PermissionError, "circuit is open"):
                runner("draft", "test", blog.SCHEMAS / "daily-blog-draft.schema.json", self.directory)


if __name__ == "__main__":
    unittest.main()
