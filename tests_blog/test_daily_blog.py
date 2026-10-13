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
from unittest.mock import Mock, patch

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
        self.payloads = {}
        self.schemas = {}

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
                    ("这段内容仅用于离线流程测试，所列信息不是现实研究证据，不能据此得出任何公司或产品的结论。" * 27 if language == "zh" else
                     "This synthetic example describes an offline fixture and preserves its stated evidence limits without making any real world research claim. " * 32) for i in range(6)) +
                    "\n[First source](https://example.org/a) [Second source](https://example.org/b)\n"}
        return {"status": "ready", "reason": "Local fixture only.", "article": article}

    def plan(self, payload):
        candidates = [{"id": f"candidate-{i}", "title": f"Synthetic candidate {i}",
            "question": f"Which synthetic evidence boundary matters for offline question {i}?",
            "reader_value": "Learn how the offline fixture records evidence boundaries.",
            "why_now": "This is a controlled test fixture, not a current news event.",
            "source_ids": ["source-a", "source-b"], "evidence_gaps": ["Synthetic inputs cannot establish real-world facts."]}
            for i in range(3)]
        kinds = ("opening", "evidence", "mechanism", "counterargument", "implications", "conclusion")
        sections = [{"id": f"section-{i}", "kind": kind, "heading_zh": f"测试章节 {i}", "heading_en": f"Section {i}",
            "purpose": "Exercise the offline editorial workflow.", "argument": "A fixture must not be mistaken for real evidence.",
            "evidence_refs": [{"source_id": "source-a", "locator": "company_pulses.json/companies/test/metrics/0"}],
            "boundaries": ["Only synthetic evidence; no public factual conclusion."],
            "zh_units_budget": 1000, "en_words_budget": 667} for i, kind in enumerate(kinds)]
        return {"status": "ready", "reason": "Offline fixture only.", "packet_sha256": payload["packet_sha256"],
            "candidates": candidates, "selected_candidate_id": "candidate-0", "selection_reason": "The fixture has two controlled sources.",
            "outline": {"title_zh": "离线选题与大纲", "title_en": "An offline topic and outline",
                "central_question": candidates[0]["question"], "working_thesis": "Only test workflow behavior.",
                "scope": "Synthetic evidence only.", "reader_takeaway": "Recognize evidence boundaries in the fixture.",
                "target_reading_minutes": 20, "sections": sections}}

    def model(self, stage, prompt, schema, directory):
        self.calls.append(stage)
        self.payloads[stage] = json.loads(prompt.split("INPUT_DATA_JSON\n", 1)[1])
        self.schemas[stage] = json.loads(schema.read_text())
        if stage == "plan":
            self.assertIn("EDITORIAL_SKILL", prompt)
            value = self.plan(json.loads(prompt.split("INPUT_DATA_JSON\n", 1)[1]))
        elif stage in ("draft", "revise", "repair_length", "revise_final"):
            self.assertTrue((self.directory / "blog-outline.md").is_file())
            self.assertTrue((self.directory / "topic-candidates.json").is_file())
            payload = json.loads(prompt.split("INPUT_DATA_JSON\n", 1)[1])
            self.assertEqual(payload["editorial_plan"]["selected_candidate_id"], "candidate-0")
            if stage == "repair_length":
                self.assertIn("measured_lengths", payload)
                self.assertLess(payload["measured_lengths"]["en"]["units"], payload["measured_lengths"]["en"]["minimum"])
            value = self.draft()
        elif stage == "humanize":
            self.assertIn("HUMANIZER_SKILL", prompt)
            self.assertIn("name: humanizer", prompt)
            value = self.draft()
            for language in ("zh", "en"):
                value["article"][language]["body_markdown"] = value["article"][language]["body_markdown"].replace(
                    "preserves its stated evidence limits", "keeps its stated evidence limits").replace(
                    "这段内容仅用于离线流程测试", "这段文字只用于离线流程测试")
        else:
            payload = json.loads(prompt.split("INPUT_DATA_JSON\n", 1)[1])
            value = {"approved": True, "facts_supported": True, "languages_consistent": True, "citations_valid": True,
                "humanizer_applied": stage in ("final_review", "final_review_revised"), "article_sha256": payload["article_sha256"],
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

    def test_every_writing_stage_has_only_the_selected_sources(self):
        self.pulses["sources"].append({"id": "source-c", "url": "https://example.org/c", "publisher": "Other issuer",
                                      "source_date": "2026-10-09", "title": "Out-of-scope record"})
        self.pulses["companies"]["test"]["metrics"].append({"source_ids": ["source-c"], "label": "Unrelated", "value": "Other"})
        (self.root / "company_pulses.json").write_text(json.dumps(self.pulses))
        self.responses["review"] = lambda value: value.update(approved=False, issues=["Fix the inline citations"])
        self.assertEqual(self.run_blog()["business_status"], "published")
        self.assertIn("source-c", [source["id"] for source in self.payloads["plan"]["packet"]["sources"]])
        for stage in ("draft", "review", "revise", "review_revised", "humanize", "final_review"):
            with self.subTest(stage=stage):
                self.assertEqual({source["id"] for source in self.payloads[stage]["packet"]["sources"]}, {"source-a", "source-b"})
                self.assertTrue(all(set(item["source_ids"]) <= {"source-a", "source-b"}
                                    for item in self.payloads[stage]["packet"]["evidence"]))
        for stage in ("draft", "revise", "humanize"):
            properties = self.schemas[stage]["properties"]["article"]["properties"]
            self.assertEqual(properties["used_source_ids"]["items"]["enum"], ["source-a", "source-b"])
            self.assertEqual(properties["fact_checks"]["items"]["properties"]["source_id"]["enum"], ["source-a", "source-b"])

    def recovery_fixture(self):
        run_id = "a" * 32
        saved = self.root / "data/runs" / run_id
        packet = blog.collect_packet(self.config, self.root, self.db, DAY)
        plan = self.plan({"packet_sha256": blog.digest(packet)})
        draft = self.draft()
        original = blog.build_draft(draft, packet, self.config, DAY, plan=plan)
        review = {"approved": False, "facts_supported": True, "languages_consistent": True, "citations_valid": False,
                  "humanizer_applied": False, "article_sha256": blog.digest(original), "packet_sha256": blog.digest(packet),
                  "issues": ["Fix the inline citations"], "reason": "Offline review fixture"}
        for stage, value in (("00-codex-plan", plan), ("01-agy-draft", draft), ("02-codex-review", review),
                             ("02b-codex-correction", draft)):
            blog.atomic_json(saved / stage / "response.json", value)
        blog.atomic_json(saved / "source-packet.json", packet)
        blog.atomic_json(saved / "blog-outline.json", plan)
        blog.atomic_json(saved / "result.json", {"success": False, "error": "Article uses sources outside the selected topic plan"})
        blog.atomic_json(saved / "recovery-corrected-draft.json", draft)
        blog.atomic_json(self.root / "data/runs/daily-blog-days" / (DAY.isoformat() + ".json"),
                         {"status": "failed", "run_id": run_id})
        self.config["workflow"]["manual_recovery"] = {"day": DAY.isoformat(), "run_id": run_id,
                                                       "draft_filename": "recovery-corrected-draft.json"}
        def live(stage, prompt, schema, directory):
            value = self.model(stage, prompt, schema, directory)
            live.calls.append(stage)
            return value
        live.calls = []
        live.settings = self.config["workflow"]
        return saved, live

    def test_manual_recovery_reuses_models_and_keeps_failed_history(self):
        saved, live = self.recovery_fixture()
        result = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(result["business_status"], "published")
        self.assertEqual(result["recovered_from"], "a" * 32)
        self.assertEqual(self.calls, ["review_revised", "humanize", "final_review"])
        self.assertEqual(len(result["model_calls"]), 7)
        self.assertEqual(blog.read_json(saved / "result.json")["success"], False)
        self.assertEqual(blog.read_json(self.directory / "recovery-audit.json")["previous_attempt"]["status"], "failed")
        again = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(again["business_status"], "already_published")
        self.assertEqual(len(self.calls), 3)

    def test_recovery_cannot_exceed_the_original_daily_budget(self):
        saved, live = self.recovery_fixture()
        self.config["workflow"]["network_policy"]["max_cli_invocations_per_day"] = 6
        with self.assertRaisesRegex(ValueError, "invocation limit"):
            blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(self.calls, [])
        marker = self.root / "data/runs/daily-blog-days" / (DAY.isoformat() + ".json")
        self.assertEqual(blog.read_json(marker)["status"], "failed")

    def test_recovery_rejects_a_different_publication_day(self):
        saved, live = self.recovery_fixture()
        packet = blog.read_json(saved / "source-packet.json")
        packet["day"] = "2026-10-09"
        blog.atomic_json(saved / "source-packet.json", packet)
        with self.assertRaisesRegex(ValueError, "publication day"):
            blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(self.calls, [])

    def test_invalid_outline_evidence_stops_before_gemini(self):
        self.responses["plan"] = lambda value: value["outline"]["sections"][0]["evidence_refs"][0].update(locator="invented/path")
        with self.assertRaisesRegex(ValueError, "locator"):
            self.run_blog()
        self.assertEqual(self.calls, ["plan"])
        self.assertFalse((self.site / "manifest.json").exists())

    def test_outline_budget_must_support_twenty_minutes(self):
        self.responses["plan"] = lambda value: value["outline"]["sections"][0].update(zh_units_budget=0)
        with self.assertRaisesRegex(ValueError, "length budget"):
            self.run_blog()
        self.assertEqual(self.calls, ["plan"])

    def test_plan_hash_mismatch_stops_before_gemini(self):
        self.responses["plan"] = lambda value: value.update(packet_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "source packet"):
            self.run_blog()
        self.assertEqual(self.calls, ["plan"])

    def test_insufficient_planning_never_calls_writer(self):
        self.responses["plan"] = lambda value: value.update(status="insufficient_evidence", candidates=[], selected_candidate_id="")
        result = self.run_blog()
        self.assertEqual(result["business_status"], "insufficient_evidence")
        self.assertEqual(result["stage"], "planning")
        self.assertTrue((self.directory / "topic-candidates.json").is_file())
        self.assertEqual(self.calls, ["plan"])

    def test_short_article_with_twenty_minute_label_is_rejected(self):
        self.config["workflow"]["max_length_repairs"] = 0
        def shorten(value):
            for language in ("zh", "en"):
                value["article"][language]["reading_time"] = "20 min read"
                value["article"][language]["body_markdown"] = "".join(f"## Section {i}\nVery short text.\n" for i in range(6))
        self.responses["draft"] = shorten
        with self.assertRaisesRegex(ValueError, "reading time"):
            self.run_blog()
        self.assertEqual(self.calls, ["plan", "draft"])

    def test_short_factual_correction_is_repaired_then_reviewed(self):
        self.responses["review"] = lambda value: value.update(approved=False, issues=["Correct the claim"])
        self.responses["revise"] = lambda value: value["article"]["en"].update(
            body_markdown="".join(f"## Section {i}\nShort corrected text.\n" for i in range(6)))
        result = self.run_blog()
        self.assertEqual(result["business_status"], "published")
        self.assertEqual(self.calls, ["plan", "draft", "review", "revise", "repair_length", "review_revised", "humanize", "final_review"])
        report = json.loads((self.directory / "02b-length-validation.json").read_text())
        self.assertLess(report["en"]["units"], report["en"]["minimum"])

    def test_short_initial_draft_is_repaired_before_review(self):
        self.responses["draft"] = lambda value: value["article"]["en"].update(
            body_markdown="".join(f"## Section {i}\nShort text.\n" for i in range(6)))
        self.assertEqual(self.run_blog()["business_status"], "published")
        self.assertEqual(self.calls, ["plan", "draft", "repair_length", "review", "humanize", "final_review"])

    def test_length_repair_is_bounded_and_cannot_change_evidence(self):
        shorten = lambda value: value["article"]["en"].update(
            body_markdown="".join(f"## Section {i}\nShort text.\n" for i in range(6)))
        self.responses.update(draft=shorten, repair_length=shorten)
        with self.assertRaisesRegex(ValueError, "reading time"):
            self.run_blog()
        self.assertEqual(self.calls, ["plan", "draft", "repair_length"])
        self.assertFalse((self.site / "manifest.json").exists())

    def test_length_repair_cannot_change_fact_metadata(self):
        self.responses["draft"] = lambda value: value["article"]["en"].update(
            body_markdown="".join(f"## Section {i}\nShort text.\n" for i in range(6)))
        self.responses["repair_length"] = lambda value: value["article"]["fact_checks"][0].update(
            claim="This invented claim must fail the metadata check.")
        with self.assertRaisesRegex(ValueError, "Length repair changed"):
            self.run_blog()
        self.assertFalse((self.site / "manifest.json").exists())

    def test_length_repair_budget_is_shared_with_factual_correction(self):
        shorten = lambda value: value["article"]["en"].update(
            body_markdown="".join(f"## Section {i}\nShort text.\n" for i in range(6)))
        self.responses.update(draft=shorten, revise=shorten)
        self.responses["review"] = lambda value: value.update(approved=False, issues=["Still unsupported"])
        with self.assertRaisesRegex(ValueError, "reading time"):
            self.run_blog()
        self.assertEqual(self.calls, ["plan", "draft", "repair_length", "review", "revise"])
        self.assertFalse((self.site / "manifest.json").exists())

    def test_humanizer_cannot_shorten_below_long_form_target(self):
        self.responses["humanize"] = lambda value: value["article"]["en"].update(
            body_markdown="".join(f"## Section {i}\nShort text.\n" for i in range(6)))
        with self.assertRaisesRegex(ValueError, "reading time"):
            self.run_blog()
        self.assertEqual(self.calls, ["plan", "draft", "review", "humanize"])

    def test_reading_estimate_excludes_url_and_code(self):
        policy = self.config["workflow"]["reading"]
        body = "A short example with a [source](https://example.org/a)."
        inflated = body.replace("https://example.org/a", "https://example.org/" + "unreadable" * 2000) + "\n```\n" + "code " * 3000 + "\n```"
        self.assertEqual(blog.editorial.reading_metrics(body, "en", policy), blog.editorial.reading_metrics(inflated, "en", policy))

    def test_plan_precedes_writer_and_publishes_both_languages_once_and_render(self):
        result = self.run_blog()
        self.assertEqual(self.calls, ["plan", "draft", "review", "humanize", "final_review"])
        self.assertEqual(result["business_status"], "published")
        self.assertNotIn("knowledge_index_error", result)
        articles = load_runtime_articles(self.site)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["automation"]["approval_kind"], "model_review")
        self.assertFalse((self.site / "approvals").exists())
        self.assertEqual(result["editorial_plan"]["candidate_count"], 3)
        self.assertEqual(result["editorial_plan"]["target_reading_minutes"], 20)
        for language in ("zh", "en"):
            self.assertGreaterEqual(result["reading_estimates"][language]["minutes"], 17)
            self.assertLessEqual(result["reading_estimates"][language]["minutes"], 23)
        self.assertNotEqual(articles[0]["reading_time"], "5 min read")
        proof = json.loads((self.site / "automation-reviews/offline-topic-outline-2026-10-10.json").read_text())
        self.assertEqual(proof["final_review"]["article_sha256"], blog.digest(proof["draft"]))
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertIsNotNone(connection.execute("SELECT 1 FROM artifacts WHERE id='daily-blog-2026-10-10'").fetchone())
        bridge_token = "offline-fixture-frontend-bridge-token"
        with patch.dict(os.environ, {"QUANT_BLOG_RUNTIME_DIR": str(self.site), "QUANT_FRONTEND_TOKEN": bridge_token}):
            from web.app import create_app
            report = self.root / "report.json"
            report.write_text(json.dumps({"schema_version": 1, "strategies": []}))
            app = create_app(report, self.root / "stats.sqlite3", self.root / "feedback.sqlite3")
            client = app.test_client()
            for language in ("zh", "en"):
                path = "/internal/frontend/articles/offline-topic-outline-2026-10-10?lang=" + language
                response = client.get(path, headers={"Authorization": "Bearer " + bridge_token})
                self.assertEqual(response.status_code, 200, path)
                self.assertIn("Offline", response.get_json()["data"]["content_html"])
                self.assertNotIn("automation", response.get_json()["data"])
            self.assertEqual(client.get("/internal/frontend/site").status_code, 401)
            response = client.get("/internal/frontend/site", headers={"Authorization": "Bearer " + bridge_token})
            self.assertIn("offline-topic-outline-2026-10-10", [item["slug"] for item in response.get_json()["data"]["articles"]])
            for path in ("/blog/offline-topic-outline-2026-10-10.md", "/blog/feed.xml", "/blog-sitemap.xml"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn(b"offline-topic-outline-2026-10-10" if path.endswith("xml") else b"Offline" if ".md" in path else b"", response.data)
        count = len(self.calls)
        self.assertEqual(self.run_blog()["business_status"], "already_published")
        self.assertEqual(len(self.calls), count)

    def test_initial_review_rejection_prevents_editing_and_publication(self):
        self.config["workflow"]["max_draft_revisions"] = 0
        self.responses["review"] = lambda value: value.update(approved=False, issues=["Unsupported claim"])
        with self.assertRaisesRegex(ValueError, "rejected"):
            self.run_blog()
        self.assertEqual(self.calls, ["plan", "draft", "review"])
        self.assertFalse((self.site / "manifest.json").exists())
        self.assertEqual(self.run_blog()["business_status"], "previous_attempt_failed")
        self.assertEqual(len(self.calls), 3)

    def test_one_factual_correction_must_pass_a_new_review_before_humanizer(self):
        self.responses["review"] = lambda value: value.update(approved=False, issues=["Correct the claim"])
        self.responses["revise"] = lambda value: value["article"].update(tags=["invented-editor-tag"])
        result = self.run_blog()
        self.assertEqual(result["business_status"], "published")
        self.assertEqual(self.calls, ["plan", "draft", "review", "revise", "review_revised", "humanize", "final_review"])
        proof = json.loads((self.site / "automation-reviews/offline-topic-outline-2026-10-10.json").read_text())
        self.assertTrue(proof["initial_review"]["approved"])
        self.assertEqual(proof["initial_review"]["article_sha256"], blog.digest(proof["original_draft"]))
        self.assertEqual(proof["draft"]["article"]["tags"], self.draft()["article"]["tags"])

    def test_correction_rejected_again_stops_without_further_attempts(self):
        reject = lambda value: value.update(approved=False, issues=["Still unsupported"])
        self.responses.update(review=reject, review_revised=reject)
        with self.assertRaisesRegex(ValueError, "rejected"):
            self.run_blog()
        self.assertEqual(self.calls, ["plan", "draft", "review", "revise", "review_revised"])
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
        self.assertEqual(self.calls, ["plan", "draft"])
        self.assertFalse((self.site / "manifest.json").exists())

    def test_final_review_must_confirm_humanizer_work(self):
        self.responses["final_review"] = lambda value: value.update(humanizer_applied=False)
        with self.assertRaisesRegex(ValueError, "humanizer"):
            self.run_blog()
        self.assertFalse((self.site / "manifest.json").exists())

    def test_final_editorial_correction_requires_an_independent_re_review(self):
        self.responses["final_review"] = lambda value: value.update(approved=False, issues=["Fix an existing evidence locator"])
        result = self.run_blog()
        self.assertEqual(result["business_status"], "published")
        self.assertEqual(self.calls[-3:], ["final_review", "revise_final", "final_review_revised"])
        proof = blog.read_json(self.site / "automation-reviews/offline-topic-outline-2026-10-10.json")
        self.assertEqual(proof["final_review"]["article_sha256"], blog.digest(proof["draft"]))

    def test_final_correction_is_bounded_and_cannot_change_sources(self):
        reject = lambda value: value.update(approved=False, issues=["Still unsupported"])
        self.responses.update(final_review=reject, final_review_revised=reject)
        with self.assertRaisesRegex(ValueError, "rejected"):
            self.run_blog()
        self.assertEqual(self.calls[-2:], ["revise_final", "final_review_revised"])
        self.assertFalse((self.site / "manifest.json").exists())

    def test_final_correction_cannot_change_topic_metadata(self):
        self.responses["final_review"] = lambda value: value.update(approved=False, issues=["Fix a locator"])
        self.responses["revise_final"] = lambda value: value["article"].update(tags=["primary-sources", "space-race"])
        with self.assertRaisesRegex(ValueError, "Final correction changed"):
            self.run_blog()
        self.assertFalse((self.site / "manifest.json").exists())

    def test_humanizer_cannot_change_fact_metadata(self):
        self.responses["humanize"] = lambda value: value["article"]["fact_checks"][0].update(claim="An altered and unsupported fabricated fact.")
        with self.assertRaisesRegex(ValueError, "Humanizer changed"):
            self.run_blog()
        self.assertFalse((self.site / "manifest.json").exists())
        self.assertEqual(self.calls, ["plan", "draft", "review", "humanize"])

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
        self.assertEqual(self.calls, ["plan", "draft"])

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

    def test_codex_uses_task_speed_and_reasoning_even_when_ignoring_user_config(self):
        schema = self.root / "command-schema.json"
        schema.write_text('{"type":"object","properties":{},"required":[]}')
        runner = blog.ModelRunner(self.config, self.root)
        for stage, key, effort in (("plan", "planner", "high"), ("review", "reviewer", None)):
            self.config["workflow"][key]["reasoning_effort"] = effort
            def start(command, **kwargs):
                output = Path(command[command.index("--output-last-message") + 1])
                output.write_text('{}')
                return Mock(returncode=0, poll=lambda: 0)
            with patch.object(blog.subprocess, "Popen", side_effect=start) as process:
                runner(stage, "Offline command fixture", schema, self.root / stage)
            command = process.call_args.args[0]
            self.assertIn("--ignore-user-config", command)
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertEqual(command[command.index("--model") + 1], "gpt-6.1-sol")
            self.assertIn('service_tier="fast"', command)
            reasoning = [value for value in command if value.startswith("model_reasoning_effort=")]
            self.assertEqual(reasoning, ['model_reasoning_effort="high"'] if effort else [])


class PresentationTests(unittest.TestCase):
    setUp = DailyBlogTests.setUp
    draft = DailyBlogTests.draft
    plan = DailyBlogTests.plan
    model = DailyBlogTests.model
    run_blog = DailyBlogTests.run_blog

    def test_publication_has_topic_url_references_and_no_process_footer(self):
        result = self.run_blog()
        self.assertEqual(result["slug"], "offline-topic-outline-2026-10-10")
        proof = blog.read_json(self.site / "automation-reviews" / (result["slug"] + ".json"))
        for localized in (proof["draft"]["article"], proof["draft"]["article"]["en"]):
            self.assertNotIn("Drafted with", localized["body_markdown"])
            self.assertNotIn("编写与复核", localized["body_markdown"])
            self.assertIn("2026-10-09", localized["body_markdown"])
        self.assertIn("## References", proof["draft"]["article"]["en"]["body_markdown"])
        self.assertTrue((self.root / "data/knowledge/topics/daily-research-blog/articles" / result["slug"] / "zh.md").is_file())

    def test_only_catalogued_inline_images_and_bounded_diagrams_are_accepted(self):
        from workflows import blog_presentation as p
        asset = {"path": "/static/images/reviewed.jpg", "source_url": "https://example.org/photo", "license_url": "https://example.org/license"}
        p.validate_markup('![Launch](/static/images/reviewed.jpg)\n```mermaid\nflowchart TB\n A --> B\n```', [asset], set())
        for body in ('## Writing and review\nDrafted with an internal model.', '![Launch](https://unknown.test/a.jpg)', '![Launch][unreviewed]', '<img src="/static/images/reviewed.jpg">',
                     '```mermaid\nflowchart TB\nclick A "https://unknown.test"\n```', '```mermaid\n%%{init: {}}%%\nflowchart TB\n A --> B\n```'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                p.validate_markup(body, [asset], set())

    def test_media_hash_is_checked_and_caption_retains_license(self):
        from workflows import blog_presentation as p
        assets = p.load_media(self.config, blog.ROOT)
        self.assertEqual(assets[0]["license"], "CC BY-SA 4.0")
        figure = p.image_figure(assets[0], "zh")
        self.assertIn(assets[0]["creator"], figure)
        self.assertIn(assets[0]["source_url"], figure)
        catalog = {"version": 1, "assets": [dict(assets[0], sha256="0" * 64)]}
        path = self.root / "media.json"
        blog.atomic_json(path, catalog)
        self.config["workflow"]["presentation"]["media_catalog"] = "media.json"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            p.load_media(self.config, self.root)

    def test_reviewed_revision_replaces_one_article_and_preserves_history(self):
        from workflows.revise_blog import replace_publication
        result = self.run_blog()
        previous = load_runtime_articles(self.site)[0]
        proof = blog.read_json(self.site / "automation-reviews" / (result["slug"] + ".json"))
        revised = deepcopy(proof["draft"])
        revised["article"]["slug"] = "topic-revised-2026-10-10"
        verdict = dict(proof["final_review"], article_sha256=blog.digest(revised))
        rejected = dict(verdict, approved=False)
        before = (self.site / "manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "rejected"):
            replace_publication(revised, proof["packet"], rejected, previous, proof, self.site, "revision", proof["skill_sha256"])
        self.assertEqual((self.site / "manifest.json").read_bytes(), before)
        published = replace_publication(revised, proof["packet"], verdict, previous, proof, self.site, "revision", proof["skill_sha256"])
        current = load_runtime_articles(self.site)
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["aliases"], [result["slug"]])
        self.assertEqual(len(list((self.site / "revisions").glob("*.json"))), 1)
        blog.record_publication(self.root, self.db, published, revised, proof["packet"])
        with sqlite3.connect(self.db) as db:
            row = db.execute("SELECT metadata_json FROM artifacts WHERE id=?", ("daily-blog-2026-10-10",)).fetchone()
        self.assertEqual(json.loads(row[0])["slug"], published["slug"])
        with self.assertRaisesRegex(ValueError, "changed"):
            replace_publication(revised, proof["packet"], verdict, previous, proof, self.site, "revision", proof["skill_sha256"])


if __name__ == "__main__":
    unittest.main()
