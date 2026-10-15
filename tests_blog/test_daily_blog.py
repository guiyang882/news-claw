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

    def test_discovered_page_is_retained_beyond_feed_window_and_not_truncated(self):
        import hashlib
        url='https://blogs.nvidia.com/blog/test-official/'
        for doc_id,kind,text,stamp in [('official-page','webpage','evidence '*1000,'2026-10-05'),
                                      ('recent-feed','feed_entry','headline snippet','2026-10-09')]:
            record={'record_type':kind,'text':text}
            relative=f'data/normalized/documents/{doc_id}.json'
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(record))
            hashed=hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            source={'type':'page' if kind=='webpage' else 'rss','name':'Official'}
            if kind=='webpage':source['discovery_document_id']='feed-discovery'
            topics=[{'topic_id':self.config['topic_ids'][0]}]
            with sqlite3.connect(self.db) as db:
                db.execute('INSERT INTO documents(id,canonical_url,title,published_at,fetched_at,content_hash,raw_path,normalized_path,created_at,source_json,topic_links_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (doc_id,url,'Official',stamp,stamp,hashed,'unused',relative,stamp,json.dumps(source),json.dumps(topics)))
        packet=blog.collect_packet(self.config,self.root,self.db,DAY)
        sources=[x for x in packet['sources'] if x['url']==url]
        self.assertEqual(len(sources),1)
        self.assertEqual(sources[0]['evidence_level'],'cached_webpage')
        evidence=next(x for x in packet['evidence'] if x['source_ids']==['doc-official-page'])
        self.assertGreater(len(evidence['text']),4000)
        self.assertEqual(sources[0]['source_date'],'2026-10-05')

    def test_locator_annotations_only_normalize_exact_source_path(self):
        from workflows.blog_planning import canonicalize_locators
        packet={'evidence':[{'source_ids':['s1'],'locator':'data/source.json'}]}
        for suffix in ['；text：paragraph','；text → paragraph','; text -> paragraph']:
            plan={'outline':{'sections':[{'evidence_refs':[{'source_id':'s1','locator':'data/source.json'+suffix}]}]}}
            corrected=canonicalize_locators(plan,packet)
            self.assertEqual(corrected['outline']['sections'][0]['evidence_refs'][0]['locator'],'data/source.json')
        for sid,loc in [('other','data/source.json；text → paragraph'),('s1','data/source.json.evil；text → paragraph')]:
            plan={'outline':{'sections':[{'evidence_refs':[{'source_id':sid,'locator':loc}]}]}}
            self.assertEqual(canonicalize_locators(plan,packet),plan)

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

    def manual_humanizer_fixture(self):
        saved, live = self.recovery_fixture()
        original = self.draft()
        edited = deepcopy(original)
        for lang in ("zh", "en"):
            edited["article"][lang]["body_markdown"] += "\nEditorial fixture revision.\n"
        audit = {"mode": "operator_applied_skill", "editor": "Offline test",
                 "changes": ["Edited both languages"], "original_filename": "02b-codex-correction/response.json",
                 "original_draft_sha256": blog.digest(original), "edited_draft_sha256": blog.digest(edited),
                 "humanizer_skill_sha256": blog.hashlib.sha256(Path(self.config["workflow"]["humanizer_skill"]).read_bytes()).hexdigest()}
        blog.atomic_json(saved / "recovery-corrected-draft.json", edited)
        blog.atomic_json(saved / "manual-edit.json", audit)
        self.config["workflow"]["manual_recovery"]["humanizer_audit_filename"] = "manual-edit.json"
        self.config["workflow"]["network_policy"]["max_cli_invocations_per_day"] = 6
        return saved, live, audit

    def test_operator_humanizer_requires_two_fresh_reviews_and_records_provenance(self):
        saved, live, audit = self.manual_humanizer_fixture()
        result = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(self.calls, ["review", "final_review"])
        self.assertEqual(len(result["model_calls"]), 6)
        self.assertEqual(result["business_status"], "published")
        self.assertEqual(result["humanizer_mode"], "operator_applied_skill")
        self.assertEqual(blog.read_json(self.directory / "03-codex-humanizer/operator-edit.json"), audit)
        baseline = self.payloads["final_review"]["original_draft"]
        self.assertNotIn("Editorial fixture revision", baseline["article"]["body_markdown"])
        self.assertIn("Editorial fixture revision", self.payloads["review"]["draft"]["article"]["body_markdown"])

    def test_operator_edit_can_compare_against_short_rejected_baseline(self):
        saved, live, audit = self.manual_humanizer_fixture()
        original = self.draft()
        original['article']['en']['body_markdown'] = ('\n'.join(f'## Section {i}\nBrief fixture.' for i in range(6))
            + '\n[First source](https://example.org/a) [Second source](https://example.org/b)\n')
        blog.atomic_json(saved / audit['original_filename'], original)
        audit['original_draft_sha256'] = blog.digest(original)
        blog.atomic_json(saved / 'manual-edit.json', audit)
        result = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(result['business_status'], 'published')
        self.assertEqual(self.calls, ['review', 'final_review'])
        self.assertIn('Brief fixture', self.payloads['final_review']['original_draft']['article']['en']['body_markdown'])

    def test_operator_edit_cannot_bypass_final_rejection(self):
        saved, live, audit = self.manual_humanizer_fixture()
        self.responses["final_review"] = lambda value: value.update(approved=False, humanizer_applied=False, issues=["Unresolved"])
        with self.assertRaisesRegex(ValueError, "Codex rejected"):
            blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(self.calls, ["review", "final_review"])
        self.assertFalse((self.site / "manifest.json").exists())

    def test_operator_edit_rejects_tampered_provenance_before_models(self):
        saved, live, audit = self.manual_humanizer_fixture()
        audit["edited_draft_sha256"] = "0" * 64
        blog.atomic_json(saved / "manual-edit.json", audit)
        with self.assertRaisesRegex(ValueError, "provenance"):
            blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(self.calls, [])

    def test_operator_edit_does_not_reset_daily_budget(self):
        saved, live, audit = self.manual_humanizer_fixture()
        self.config["workflow"]["network_policy"]["max_cli_invocations_per_day"] = 5
        with self.assertRaisesRegex(ValueError, "invocation limit"):
            blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(self.calls, [])

    def test_manual_recovery_reuses_models_and_keeps_failed_history(self):
        saved, live = self.recovery_fixture()
        result = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(result["business_status"], "published")
        self.assertEqual(result["recovered_from"], "a" * 32)
        self.assertEqual(self.calls, ["review", "humanize", "final_review"])
        self.assertEqual(len(result["model_calls"]), 7)
        self.assertEqual(blog.read_json(saved / "result.json")["success"], False)
        self.assertEqual(blog.read_json(self.directory / "recovery-audit.json")["previous_attempt"]["status"], "failed")
        again = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(again["business_status"], "already_published")
        self.assertEqual(len(self.calls), 3)

    def test_length_failure_before_humanizer_can_resume_with_fresh_reviews(self):
        saved, live = self.recovery_fixture()
        blog.atomic_json(saved / "result.json", {"success": False,
            "error": "en article does not meet the approximate reading time target: 3135 units; required 3201–4600"})
        self.assertFalse((saved / "03-codex-humanizer/response.json").exists())
        result = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(result["business_status"], "published")
        self.assertEqual(self.calls, ["review", "humanize", "final_review"])
        self.assertEqual(len(result["model_calls"]), 7)

    def test_rejected_early_review_can_be_backfilled_with_fresh_verdicts(self):
        saved, live = self.recovery_fixture()
        blog.atomic_json(saved / "result.json", {"success": False, "error": "Codex rejected the article; publication stopped"})
        rejected = blog.read_json(saved / "02-codex-review/response.json")
        blog.atomic_json(saved / "02c-codex-re-review/response.json", rejected)
        packet_bytes = (saved / "source-packet.json").read_bytes()
        result = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(result["business_status"], "published")
        self.assertEqual(self.calls, ["review", "humanize", "final_review"])
        self.assertEqual(len(result["model_calls"]), 8)
        self.assertEqual((saved / "source-packet.json").read_bytes(), packet_bytes)
        article = blog.read_json(self.site / "manifest.json")["articles"][0]
        self.assertEqual(article["published_at"], DAY.isoformat())
        self.assertGreater(article["updated_at"], article["published_at"])
        final = blog.read_json(self.directory / "final-draft.json")
        self.assertIn("补发于", final["article"]["body_markdown"])
        self.assertIn("published on", final["article"]["en"]["body_markdown"])

    def test_recovery_still_stops_on_a_new_review_rejection(self):
        saved, live = self.recovery_fixture()
        self.config["workflow"]["max_draft_revisions"] = 0
        self.responses["review"] = lambda value: value.update(approved=False, issues=["Still unsupported"])
        with self.assertRaisesRegex(ValueError, "Codex rejected"):
            blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertFalse((self.site / "manifest.json").exists())

    def test_cli_only_backfills_an_explicit_manual_run(self):
        self.recovery_fixture()
        for trigger in ("manual", "cron"):
            with self.subTest(trigger=trigger):
                connection = Mock()
                rows = [(json.dumps(self.config), True, "news-claw"),
                        (json.dumps({"trigger": trigger}),), ("failed-run",)]
                connection.execute.side_effect = [Mock(fetchone=Mock(return_value=row)) for row in rows]
                env = {"NEWS_CLAW_ROOT": str(self.root), "NEWS_CLAW_DB": str(self.db),
                       "NEWS_CLAW_RUN_ID": "b" * 32, "NEWS_CLAW_TASK_ID": "daily-blog-agy-codex",
                       "NEWS_CLAW_TASK_CONFIG_PATH": "", "NEWS_CLAW_RESULT_PATH": ""}
                with patch.dict(os.environ, env), patch.object(sys, "argv", ["daily_blog"]), \
                     patch.object(blog.sqlite3, "connect", return_value=connection), \
                     patch.object(blog, "run", return_value={"success": True}) as run:
                    self.assertEqual(blog.main(), 0)
                self.assertEqual(run.call_args.kwargs["day"], DAY if trigger == "manual" else None)
                self.assertEqual("manual_recovery" in run.call_args.args[0]["workflow"], trigger == "manual")

    def test_reading_lower_bound_matches_displayed_minutes(self):
        policy = self.config["workflow"]["reading"]
        limits = blog.editorial.length_requirements(policy)
        for language, text in (("zh", "字"), ("en", "word ")):
            minimum = limits[language]["minimum"]
            metric = blog.editorial.reading_metrics(text * minimum, language, policy)
            below = blog.editorial.reading_metrics(text * (minimum - 1), language, policy)
            self.assertEqual(metric["minutes"], policy["target_minutes"] - policy["tolerance_minutes"])
            self.assertEqual(below["minutes"], metric["minutes"] - 1)

    def test_unchanged_humanized_checkpoint_only_needs_final_review(self):
        saved, live = self.recovery_fixture()
        packet = blog.read_json(saved / "source-packet.json")
        plan = blog.read_json(saved / "blog-outline.json")
        config = deepcopy(self.config)
        config["workflow"]["recovery_updated_at"] = blog.datetime.now(blog.ZoneInfo(config["timezone"])).date().isoformat()
        original = blog.build_draft(self.draft(), packet, config, DAY, plan=plan)
        review = blog.read_json(saved / "02-codex-review/response.json")
        review.update(approved=True, citations_valid=True, issues=[], article_sha256=blog.digest(original))
        blog.atomic_json(saved / "02-codex-review/response.json", review)
        blog.atomic_json(saved / "reviewed-draft.json", original)
        blog.atomic_json(saved / "03-codex-humanizer/response.json", self.draft())
        blog.atomic_json(saved / "result.json", {"error": "zh article does not meet the approximate reading time target: 5052 units; required 5100–6900"})
        result = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(self.calls, ["final_review"])
        self.assertEqual(len(result["model_calls"]), 6)
        self.assertEqual(result["business_status"], "published")

    def test_budget_failure_after_approved_revision_resumes_exact_final_review(self):
        saved, live = self.recovery_fixture()
        packet = blog.read_json(saved / "source-packet.json")
        plan = blog.read_json(saved / "blog-outline.json")
        config = deepcopy(self.config)
        config["workflow"]["recovery_updated_at"] = blog.datetime.now(blog.ZoneInfo(config["timezone"])).date().isoformat()
        original = blog.build_draft(self.draft(), packet, config, DAY, plan=plan)
        review = blog.read_json(saved / "02-codex-review/response.json")
        review.update(approved=True, citations_valid=True, issues=[], article_sha256=blog.digest(original))
        blog.atomic_json(saved / "02c-codex-re-review/response.json", review)
        blog.atomic_json(saved / "reviewed-draft.json", original)
        blog.atomic_json(saved / "03-codex-humanizer/response.json", self.draft())
        blog.atomic_json(saved / "result.json", {"error": "Model invocation limit reached"})
        result = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(self.calls, ["final_review"])
        self.assertEqual(len(result["model_calls"]), 7)
        self.assertEqual(result["business_status"], "published")

    def test_recovery_budget_counts_ancestors_but_not_replayed_responses(self):
        saved, live = self.recovery_fixture()
        child = saved.parent / ("b" * 32)
        blog.atomic_json(child / "recovery-audit.json", {"recovered_from": saved.name})
        for stage in ("00-codex-plan", "01-agy-draft"):
            blog.atomic_json(child / stage / "response.json", blog.read_json(saved / stage / "response.json"))
            blog.atomic_json(child / stage / "reused-stage.json", {"model_called": False})
        blog.atomic_json(child / "02-codex-review/response.json", {})
        stages = blog.RecoveryStages(live, child, self.draft())
        self.assertEqual(len(stages.calls), 5)
        self.config["workflow"]["network_policy"]["max_cli_invocations_per_day"] = 7
        with self.assertRaisesRegex(ValueError, "invocation limit"):
            blog.RecoveryStages(live, child, self.draft())

    def test_manual_replan_requires_new_evidence_and_retains_budget(self):
        saved, live = self.recovery_fixture()
        self.config["workflow"].pop("manual_recovery")
        self.config["workflow"]["manual_replan"] = {"day": DAY.isoformat(), "run_id": saved.name}
        blog.atomic_json(saved / "result.json", {"business_status": "insufficient_evidence", "day": DAY.isoformat()})
        marker = self.root / "data/runs/daily-blog-days" / (DAY.isoformat() + ".json")
        blog.atomic_json(marker, {"status": "insufficient_evidence", "run_id": saved.name})
        with self.assertRaisesRegex(ValueError, "changed source evidence"):
            blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(self.calls, [])
        self.pulses["companies"]["test"]["metrics"][0]["value"] = "Additional cached evidence"
        (self.root / "company_pulses.json").write_text(json.dumps(self.pulses))
        result = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(result["business_status"], "published")
        self.assertEqual(result["recovered_from"], saved.name)
        self.assertEqual(len(result["model_calls"]), 9)
        self.assertEqual(blog.read_json(saved / "result.json")["business_status"], "insufficient_evidence")
        self.assertEqual(blog.read_json(self.directory / "recovery-audit.json")["kind"], "manual_evidence_replan")

    def test_pinned_primary_disclosure_keeps_fuller_text_and_its_original_date(self):
        url = "https://example.org/quarterly-report"
        self.config["workflow"]["inputs"].update(primary_source_urls=[url], primary_max_text_chars=18000)
        record = {"canonical_url": url, "title": "Dated quarterly report", "published_at": "2026-07-30",
                  "record_type": "webpage", "text": "Disclosed financial evidence. " * 1000}
        relative = "data/normalized/documents/primary.json"
        blog.atomic_json(self.root / relative, record)
        checksum = blog.hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO documents(id,canonical_url,title,published_at,fetched_at,content_hash,raw_path,normalized_path,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       ("primary-fixture",url,record["title"],record["published_at"],"2026-07-30",checksum,"unused",relative,"2026-07-30"))
        packet = blog.collect_packet(self.config, self.root, self.db, DAY)
        item = next(e for e in packet["evidence"] if e["locator"] == relative)
        self.assertEqual(len(item["text"]), 18000)
        source = next(s for s in packet["sources"] if s["id"] == "doc-primary-fixture")
        self.assertEqual(source["source_date"], "2026-07-30")
        self.assertEqual(source["evidence_level"], "cached_webpage")
        (self.root / relative).write_text(json.dumps({**record, "text": "tampered"}))
        with self.assertRaisesRegex(ValueError, "hash differs"):
            blog.collect_packet(self.config, self.root, self.db, DAY)

    def test_plan_locator_annotations_normalize_only_existing_source_paths(self):
        saved, live = self.recovery_fixture()
        packet = blog.read_json(saved / "source-packet.json")
        plan = blog.read_json(saved / "00-codex-plan/response.json")
        original = plan["outline"]["sections"][0]["evidence_refs"][0]["locator"]
        plan["outline"]["sections"][0]["evidence_refs"][0]["locator"] += "；text：section description"
        repaired = blog.editorial.canonicalize_locators(plan, packet)
        self.assertEqual(repaired["outline"]["sections"][0]["evidence_refs"][0]["locator"], original)
        self.assertIn("；text：", plan["outline"]["sections"][0]["evidence_refs"][0]["locator"])
        plan["outline"]["sections"][0]["evidence_refs"][0]["locator"] = "invented/path；text：description"
        repaired = blog.editorial.canonicalize_locators(plan, packet)
        with self.assertRaisesRegex(ValueError, "locator"):
            blog.editorial.validate_plan(repaired, packet, self.config["workflow"], packet_sha256=blog.digest(packet))

    def test_plan_validation_failure_resumes_without_replanning_or_losing_budget(self):
        saved, live = self.recovery_fixture()
        self.config["workflow"]["manual_recovery"] = {"day": DAY.isoformat(), "run_id": saved.name, "resume_stage": "plan"}
        blog.atomic_json(saved / "result.json", {"error": "Outline evidence locator does not exist in the source packet"})
        plan = blog.read_json(saved / "00-codex-plan/response.json")
        plan["outline"]["sections"][0]["evidence_refs"][0]["locator"] += "；text：paragraph annotation"
        blog.atomic_json(saved / "00-codex-plan/response.json", plan)
        result = blog.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=live, day=DAY)
        self.assertEqual(self.calls, ["draft", "review", "humanize", "final_review"])
        self.assertEqual(len(result["model_calls"]), 8)
        self.assertEqual(result["business_status"], "published")

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
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_attention"])
        self.assertIn("not published", result["error"])
        self.assertFalse(self.run_blog()["success"])
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
            self.assertEqual(client.get("/blog/offline-topic-outline-2026-10-10.md").status_code, 404)
            for path in ("/blog/feed.xml", "/blog-sitemap.xml"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn(b"offline-topic-outline-2026-10-10", response.data)
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

    def test_truncated_writer_is_counted_and_partial_output_is_never_accepted(self):
        self.config["workflow"]["network_policy"]["max_cli_invocations_per_day"] = 1
        runner = blog.ModelRunner(self.config, self.root)
        schema = self.root / "empty-schema.json"
        schema.write_text('{"type":"object","properties":{},"required":[]}')
        stage = self.root / "data/runs" / ("f" * 32) / "01-agy-summary"
        def start(command, **kwargs):
            envelope = {"status": "ERROR", "error": "Response cut off: output token limit",
                        "structured_output": {}, "usage": {"total_tokens": 152015}}
            kwargs["stdout"].write(json.dumps(envelope).encode())
            kwargs["stdout"].flush()
            return Mock(returncode=0, poll=lambda: 0)
        with patch.object(blog.subprocess, "Popen", side_effect=start) as process:
            with self.assertRaisesRegex(ValueError, "truncated"):
                runner("draft", "Offline fixture", schema, stage)
        self.assertEqual(runner.calls[0]["usage"]["total_tokens"], 152015)
        self.assertEqual(runner.calls[0]["status"], "failed")
        self.assertFalse((stage / "response.json").exists())
        self.assertEqual(len(blog.previous_model_calls(stage.parent)), 1)
        # A subsequent valid response for the same recorded stage must not double count it.
        blog.atomic_json(stage / "response.json", {})
        self.assertEqual(len(blog.previous_model_calls(stage.parent)), 1)
        with self.assertRaisesRegex(ValueError, "invocation limit"):
            runner("draft", "No retry", schema, stage)

    def test_nonzero_writer_exit_retains_usage(self):
        runner = blog.ModelRunner(self.config, self.root)
        schema = self.root / "empty-schema.json"
        schema.write_text('{"type":"object","properties":{},"required":[]}')
        def start(command, **kwargs):
            kwargs["stdout"].write(json.dumps({"status": "ERROR", "usage": {"total_tokens": 42}}).encode())
            kwargs["stdout"].flush()
            return Mock(returncode=1, poll=lambda: 1)
        with patch.object(blog.subprocess, "Popen", side_effect=start):
            with self.assertRaisesRegex(RuntimeError, "exited with status 1"):
                runner("draft", "Offline fixture", schema, self.directory)
        self.assertEqual(runner.calls[0]["usage"]["total_tokens"], 42)
        self.assertEqual(runner.calls[0]["status"], "failed")

    def test_schema_validator_accepts_numbers_but_not_booleans(self):
        numeric = {"type": "number", "minimum": 0, "maximum": 100}
        for value in (0, 53, 53.5):
            blog.validate_shape(value, numeric)
        for value in (True, "53", 101):
            with self.assertRaises(ValueError):
                blog.validate_shape(value, numeric)

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

    def test_references_do_not_present_unverified_metadata_as_publication_dates(self):
        from workflows.blog_presentation import with_references
        source = {'title': 'Source — report', 'url': 'https://example.org/a', 'publisher': 'Publisher',
                  'source_date': '2026-10-15', 'snapshot_as_of': '2026-10-14'}
        for lang in ('zh', 'en'):
            rendered = with_references('Body', [source], lang)
            self.assertNotIn('2026-10', rendered)
            self.assertNotIn('—', rendered)
            self.assertIn('[Source :  report](https://example.org/a)', rendered)

    def test_publication_has_topic_url_references_and_no_process_footer(self):
        result = self.run_blog()
        self.assertEqual(result["slug"], "offline-topic-outline-2026-10-10")
        proof = blog.read_json(self.site / "automation-reviews" / (result["slug"] + ".json"))
        for localized in (proof["draft"]["article"], proof["draft"]["article"]["en"]):
            self.assertNotIn("Drafted with", localized["body_markdown"])
            self.assertNotIn("编写与复核", localized["body_markdown"])
            self.assertNotIn("2026-10-09", localized["body_markdown"].split("## ")[-1])
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

    def test_excluded_photo_mentions_do_not_attach_unrelated_media(self):
        from workflows import blog_presentation as p
        assets = p.load_media(self.config, blog.ROOT)
        plan = self.plan({"packet_sha256": "fixture"})
        plan["outline"].update(title_zh="Starship 的运力如何转成 Starlink 服务？",
                               title_en="When does Starship capacity become usable Starlink service?",
                               central_question="Which deployment and service evidence is still needed?")
        plan["outline"]["sections"][-1]["boundaries"].append("Omit the unrelated Electron / Rocket Lab CAPSTONE launch photo.")
        packet = {"approved_media": assets}
        self.assertEqual(p.selected_media(packet, plan), [])
        self.assertEqual(p.with_hero("Article without a photo.", p.selected_media(packet, plan), "en"), "Article without a photo.")
        plan["outline"]["sections"][-1]["boundaries"].pop()
        plan["outline"].update(title_zh="Rocket Lab 订单怎样兑现？", central_question="What would validate Rocket Lab's order conversion?")
        plan["outline"]["title_en"] = "What must Rocket Lab orders deliver for shareholders?"
        self.assertEqual(p.selected_media(packet, plan)[0]["id"], "electron-capstone-2022")

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
