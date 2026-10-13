"""Offline tests for evidence scope, approval and repeat-call protection."""

from copy import deepcopy
from contextlib import closing
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from workflows import daily_blog as blog
from workflows import topic_summary as summary


DAY = date(2026, 10, 13)


class TopicSummaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / "news.sqlite3"
        with closing(sqlite3.connect(self.db)) as connection, connection:
            for path in sorted((blog.ROOT / "sql/migrations").glob("*.sql")):
                connection.executescript(path.read_text())
            for tid in ("ai-products-attention-feedback", "space-race"):
                topic = {"id": tid, "name": tid, "questions": ["Which claims are supported?"], "analysis_rules": []}
                connection.execute("INSERT INTO topics(id,name,config_json,created_at,updated_at) VALUES (?,?,?,?,?)",
                                   (tid, tid, json.dumps(topic), blog.now(), blog.now()))
        self.config = json.loads((blog.ROOT / "config/tasks/ai-products-gemini-summary.json").read_text())
        self.config["workflow"]["min_model_interval_seconds"] = 0
        self.config["workflow"]["max_summary_revisions"] = 0
        self.directory = self.root / "data/runs/test-run"
        self.add_document("a")
        self.add_document("b")
        self.runner = Mock()
        self.runner.calls = []
        self.change_draft = lambda value: None
        self.approved = True
        self.approve_correction = False
        self.runner.side_effect = self.model

    def add_document(self, name, topic="ai-products-attention-feedback", stamp="2026-10-12", kind="feed_item"):
        record = {"record_type": kind, "text": "An attributed synthetic headline; not a verified real event.",
                  "title": name, "canonical_url": "https://example.org/" + name, "published_at": stamp}
        content_hash = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        sid = hashlib.sha256(name.encode()).hexdigest()
        path = self.root / "data/normalized/documents" / (sid + ".json")
        blog.atomic_json(path, record)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("""INSERT INTO documents(id,source_json,canonical_url,title,published_at,fetched_at,
                content_hash,raw_path,normalized_path,topic_links_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, '{"name":"Synthetic issuer"}', record["canonical_url"], name, stamp, stamp, content_hash,
                 "unused", str(path.relative_to(self.root)), json.dumps([{"topic_id": topic}]), blog.now()))
        return path

    def packet(self):
        return summary.collect_packet(self.config, self.root, self.db, DAY)

    def draft(self, packet):
        report = {"topic_id": "ai-products-attention-feedback", "summary": "Two attributed headline leads require original texts.",
                  "observations": [], "timeline": [], "inferences": [], "entities": [], "relations": [],
                  "evidence_gaps": ["No primary text or representative user sample."], "used_source_ids": []}
        for item in packet["evidence"]:
            sid = item["source_ids"][0]
            report["observations"].append({"kind": "headline_lead", "claim": "An unverified synthetic headline was collected.",
                "boundary": item["boundary"], "source_refs": [{"source_id": sid, "locator": item["locator"]}]})
            report["used_source_ids"].append(sid)
        return {"status": "ready", "reason": "Synthetic fixture only.", "packet_sha256": blog.digest(packet), "topics": [report]}

    def model(self, stage, prompt, schema, directory):
        self.runner.calls.append({"stage": stage})
        data = json.loads(prompt.split("INPUT_DATA_JSON\n", 1)[1])
        if stage in ("draft", "correct"):
            value = self.draft(data["packet"])
            if stage == "draft":
                self.change_draft(value)
            elif self.approve_correction:
                self.approved = True
        else:
            value = {"approved": self.approved, "facts_supported": self.approved, "references_valid": True,
                     "boundaries_preserved": True, "summary_sha256": data["summary_sha256"],
                     "packet_sha256": data["packet_sha256"], "issues": [] if self.approved else ["Unsupported overview"],
                     "reason": "Offline fixture verdict"}
        blog.atomic_json(directory / "response.json", value)
        return value

    def run_summary(self, day=DAY):
        return summary.run(self.config, self.root, self.db, self.directory, execute=True, model_runner=self.runner, day=day)

    def artifact_count(self):
        with closing(sqlite3.connect(self.db)) as connection:
            return connection.execute("SELECT count(*) FROM artifacts").fetchone()[0]

    def test_topic_filter_precedes_limit_and_excludes_future_records(self):
        for i in range(6):
            self.add_document("unrelated" + str(i), "space-race", "2026-10-13")
        self.add_document("future", stamp="2026-10-14")
        self.config["workflow"]["inputs"]["max_documents"] = 2
        self.assertEqual({s["title"] for s in self.packet()["sources"]}, {"a", "b"})

    def test_hash_mismatch_stops_before_model_calls(self):
        path = next(self.root.glob("data/normalized/documents/*.json"))
        value = blog.read_json(path)
        value["text"] = "changed"
        blog.atomic_json(path, value)
        with self.assertRaisesRegex(ValueError, "hash differs"):
            self.run_summary()
        self.runner.assert_not_called()

    def test_approved_knowledge_and_daily_repeat_use_no_more_calls(self):
        result = self.run_summary()
        self.assertEqual(result["business_status"], "knowledge_updated")
        self.assertEqual(self.artifact_count(), 1)
        self.assertTrue((self.root / result["artifact_paths"][0]).with_suffix(".md").is_file())
        self.assertEqual(self.run_summary(date(2026, 10, 14))["business_status"], "unchanged_inputs")
        self.assertEqual(self.runner.call_count, 2)

    def test_review_rejection_leaves_no_knowledge_and_no_unattended_retry(self):
        self.approved = False
        self.assertFalse(self.run_summary()["success"])
        self.assertEqual(self.artifact_count(), 0)
        self.assertFalse(list(self.root.glob("data/knowledge/**/*.json")))
        self.assertEqual(self.run_summary()["business_status"], "previous_attempt_failed")
        self.assertEqual(self.runner.call_count, 2)

    def test_headline_cannot_be_promoted_to_a_fact(self):
        packet = self.packet()
        raw = self.draft(packet)
        raw["topics"][0]["observations"][0]["kind"] = "reported_fact"
        with self.assertRaisesRegex(ValueError, "promoted"):
            summary.validate_summary(raw, packet)
        prepared = summary.prepare_summary(raw, packet)
        self.assertEqual(prepared["topics"][0]["observations"][0]["kind"], "headline_lead")
        self.approved = False
        self.change_draft = lambda value: value["topics"][0]["observations"][0].update(kind="reported_fact")
        self.assertFalse(self.run_summary()["success"])
        self.assertEqual(self.artifact_count(), 0)

    def test_one_correction_requires_an_independent_approved_review(self):
        self.config["workflow"]["max_summary_revisions"] = 1
        self.approved = False
        self.approve_correction = True
        result = self.run_summary()
        self.assertEqual(result["business_status"], "knowledge_updated")
        self.assertTrue(result["summary_revised"])
        self.assertEqual([c["stage"] for c in self.runner.calls], ["draft", "review", "correct", "review_corrected"])

    def test_rejection_after_one_correction_stops_with_no_knowledge(self):
        self.config["workflow"]["max_summary_revisions"] = 1
        self.approved = False
        self.assertFalse(self.run_summary()["success"])
        self.assertEqual([c["stage"] for c in self.runner.calls], ["draft", "review", "correct", "review_corrected"])
        self.assertEqual(self.artifact_count(), 0)

    def test_local_validation_correction_still_requires_codex_review(self):
        self.config["workflow"]["max_summary_revisions"] = 1
        self.change_draft = lambda value: value["topics"][0]["observations"][0]["source_refs"][0].update(locator="unknown")
        self.assertEqual(self.run_summary()["business_status"], "knowledge_updated")
        self.assertEqual([c["stage"] for c in self.runner.calls], ["draft", "correct", "review"])

    def test_bad_locator_and_future_completed_event_are_rejected(self):
        packet = self.packet()
        draft = self.draft(packet)
        ref = draft["topics"][0]["observations"][0]["source_refs"][0]
        ref["locator"] = "invented"
        with self.assertRaisesRegex(ValueError, "reference"):
            summary.validate_summary(draft, packet)
        draft = self.draft(packet)
        draft["topics"][0]["timeline"].append({"event_date": "2027-01-01", "state": "reported_event", "event": "Synthetic target",
            "boundary": "not completed", "source_refs": deepcopy(draft["topics"][0]["observations"][0]["source_refs"])})
        with self.assertRaisesRegex(ValueError, "future target"):
            summary.validate_summary(draft, packet)

    def test_timeline_accepts_supplied_iso_timestamp_and_checks_future_day(self):
        packet = self.packet()
        draft = self.draft(packet)
        event = {"event_date": "2026-10-13T08:22:51+00:00", "state": "headline_lead", "event": "An attributed headline",
                 "boundary": "Unverified lead", "source_refs": deepcopy(draft["topics"][0]["observations"][0]["source_refs"])}
        draft["topics"][0]["timeline"].append(event)
        summary.validate_summary(draft, packet)
        event.update(event_date="2027-01-01T08:22:51Z", state="reported_event")
        with self.assertRaisesRegex(ValueError, "future target"):
            summary.validate_summary(draft, packet)
        event["state"] = "announced_target"
        summary.validate_summary(draft, packet)

    def test_graph_nodes_are_derived_before_review_without_mutating_raw_candidate(self):
        packet = self.packet()
        raw = self.draft(packet)
        raw["topics"][0]["entities"] = ["issuer"]
        raw["topics"][0]["relations"] = [{"from_entity": "issuer", "to_entity": "product", "relationship": "An attributed headline lead",
            "boundary": "Unverified", "source_refs": deepcopy(raw["topics"][0]["observations"][0]["source_refs"])}]
        draft = summary.prepare_summary(raw, packet)
        self.assertEqual(draft["topics"][0]["entities"], ["issuer", "product"])
        self.assertEqual(raw["topics"][0]["entities"], ["issuer"])

    def test_partial_calendar_date_is_preserved_without_guessing_year(self):
        packet = self.packet()
        raw = self.draft(packet)
        raw["topics"][0]["timeline"] = [{"event_date": "October 19", "state": "announced_target", "event": "A title mentions a target",
            "boundary": "Year not supplied", "source_refs": deepcopy(raw["topics"][0]["observations"][0]["source_refs"])}]
        draft = summary.prepare_summary(raw, packet)
        self.assertEqual(draft["topics"][0]["timeline"][0]["event_date"], "")
        self.assertIn("October 19", draft["topics"][0]["timeline"][0]["boundary"])
        self.assertEqual(raw["topics"][0]["timeline"][0]["event_date"], "October 19")

    def test_explicit_recovery_reuses_saved_gemini_and_preserves_failure(self):
        saved_id = "a" * 32
        self.directory = self.root / "data/runs" / saved_id
        self.approved = False
        self.assertFalse(self.run_summary()["success"])
        failed = blog.read_json(self.directory / "02-codex-review/response.json")
        self.approved = True
        directory = self.root / "data/runs" / ("b" * 32)
        result = summary.run(self.config, self.root, self.db, directory, execute=True,
                             model_runner=self.runner, day=DAY, resume_run=saved_id)
        self.assertEqual(result["business_status"], "knowledge_updated")
        self.assertEqual(result["reused_gemini_run"], saved_id)
        self.assertEqual([call["stage"] for call in self.runner.calls], ["draft", "review", "review"])
        self.assertEqual(blog.read_json(self.directory / "02-codex-review/response.json"), failed)
        self.assertTrue((directory / "recovery-audit.json").is_file())

    def test_recovery_reuses_existing_codex_correction_for_fresh_review(self):
        saved_id = "a" * 32
        self.directory = self.root / "data/runs" / saved_id
        self.config["workflow"]["max_summary_revisions"] = 1
        self.approved = False
        self.assertFalse(self.run_summary()["success"])
        self.approved = True
        result = summary.run(self.config, self.root, self.db, self.root / "data/runs" / ("b" * 32),
                             execute=True, model_runner=self.runner, day=DAY, resume_run=saved_id)
        self.assertEqual(result["business_status"], "knowledge_updated")
        self.assertEqual(result["reused_candidate_stage"], "03-codex-correction")
        self.assertEqual([c["stage"] for c in self.runner.calls], ["draft", "review", "correct", "review_corrected", "review"])

    def test_blog_reads_provenance_and_omits_tampered_summary(self):
        result = self.run_summary()
        contexts, sources, evidence = summary.reviewed_context(self.root, self.db, DAY, self.config["topic_ids"])
        self.assertEqual(len(contexts), 1)
        self.assertEqual(len(sources), 2)
        self.assertEqual(len(evidence), 2)
        cfg = deepcopy(self.config)
        cfg["workflow"]["inputs"].update(company_pulses=str(self.root / "absent.json"), news_timeline=str(self.root / "absent.json"),
                                          max_reviewed_topic_summaries=5, reviewed_topic_lookback_days=2)
        packet = blog.collect_packet(cfg, self.root, self.db, DAY)
        self.assertEqual(len(packet["reviewed_topic_summaries"]), 1)
        path = self.root / result["artifact_paths"][0]
        bundle = blog.read_json(path)
        bundle["draft"]["topics"][0]["summary"] = "Altered after review"
        blog.atomic_json(path, bundle)
        self.assertEqual(summary.reviewed_context(self.root, self.db, DAY, self.config["topic_ids"]), ([], [], []))

    def test_missing_packet_is_not_treated_as_reviewed_context(self):
        self.run_summary()
        (self.directory / "source-packet.json").unlink()
        self.assertEqual(summary.reviewed_context(self.root, self.db, DAY, self.config["topic_ids"]), ([], [], []))

    def test_writing_stage_gets_original_selected_evidence_without_summaries(self):
        packet = self.packet()
        packet["reviewed_topic_summaries"] = [{"report": {"summary": "Secondary analysis only"}}]
        packet["approved_media"] = []
        sid = packet["sources"][0]["id"]
        plan = {"selected_candidate_id": "chosen", "candidates": [{"id": "chosen", "source_ids": [sid]}],
                "outline": {"title_zh": "测试", "title_en": "Fixture", "central_question": "What is supported?"}}
        selected = blog.selected_packet(packet, plan)
        self.assertNotIn("reviewed_topic_summaries", selected)
        self.assertEqual([source["id"] for source in selected["sources"]], [sid])
        self.assertTrue(all(item["source_ids"] == [sid] for item in selected["evidence"]))

    def test_provider_denial_remains_shared_with_daily_blog(self):
        runner = blog.ModelRunner(self.config, self.root)
        blog.atomic_json(self.root / "data/runs/blog-provider-policy/agy.blocked.json", {"reason": "quota denial"})
        with patch.object(blog.subprocess, "Popen", side_effect=AssertionError("must not invoke")):
            with self.assertRaisesRegex(PermissionError, "circuit is open"):
                runner("draft", "test", summary.SCHEMAS / "topic-summary.schema.json", self.directory)

    def test_codex_uses_medium_default_full_permissions_and_four_call_limit(self):
        schema = self.root / "schema.json"
        blog.atomic_json(schema, {"type": "object", "properties": {}, "required": []})
        runner = blog.ModelRunner(self.config, self.root)
        def start(command, **kwargs):
            Path(command[command.index("--output-last-message") + 1]).write_text("{}")
            return Mock(returncode=0, poll=lambda: 0)
        with patch.object(blog.subprocess, "Popen", side_effect=start) as process:
            runner("review", "offline", schema, self.directory)
        command = process.call_args.args[0]
        self.assertIn('--dangerously-bypass-approvals-and-sandbox', command)
        self.assertIn('service_tier="default"', command)
        self.assertIn('model_reasoning_effort="medium"', command)
        runner.calls.extend([{"stage": "draft"}] * 3)
        with self.assertRaisesRegex(ValueError, "invocation limit"):
            runner("review", "offline", schema, self.directory)

    def test_agy_uses_full_permissions_and_records_reported_usage(self):
        schema = self.root / "schema.json"
        blog.atomic_json(schema, {"type": "object", "properties": {}, "required": []})
        runner = blog.ModelRunner(self.config, self.root)
        def start(command, **kwargs):
            kwargs["stdout"].write(json.dumps({"status": "SUCCESS", "structured_output": {},
                                             "usage": {"total_tokens": 42, "cost": "not a token count"}}).encode())
            kwargs["stdout"].flush()
            return Mock(returncode=0, poll=lambda: 0)
        with patch.object(blog.subprocess, "Popen", side_effect=start) as process:
            runner("draft", "offline", schema, self.directory)
        command = process.call_args.args[0]
        self.assertIn("--dangerously-skip-permissions", command)
        self.assertIn("--disable-slash-commands", command)
        self.assertEqual(command[command.index("--model") + 1], "gemini-3.8-flash-high")
        self.assertEqual(runner.calls[0]["usage"], {"total_tokens": 42})


if __name__ == "__main__":
    unittest.main()
