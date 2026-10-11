"""Offline integration tests: real Go runner + Scrapy against localhost."""

import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import closing
from unittest.mock import Mock
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = str(REPO / ".venv/bin/python")
BINARY = str(REPO / "bin/news-claw")


class CollectionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / "test.sqlite3"
        with closing(sqlite3.connect(self.db)) as connection, connection:
            for migration in sorted((REPO / "sql/migrations").glob("*.sql")):
                connection.executescript(migration.read_text())
            connection.execute("INSERT INTO schema_migrations VALUES (4,'test','2026-10-10T00:00:00Z')")
        self.requests = []
        self.robots = b"User-agent: *\nAllow: /\n"
        self.http_lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with owner.http_lock:
                    owner.requests.append((self.path, time.time()))
                if self.path == "/robots.txt":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(owner.robots)
                    return
                if self.path == "/denied":
                    self.send_response(429)
                    self.send_header("Retry-After", "60")
                    self.end_headers()
                    self.wfile.write(b"limited")
                    return
                if self.path == "/forbidden":
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(b"denied")
                    return
                if self.path == "/rss-redirect":
                    self.send_response(302)
                    self.send_header("Location", "/rss-target")
                    self.end_headers()
                    return
                if self.path == "/federal":
                    body = json.dumps({"results": [
                        {"title": "China semiconductor export controls", "html_url": owner.base + "/notice-a",
                         "publication_date": datetime.now(timezone.utc).date().isoformat(), "abstract": "Export license changes."},
                        {"title": "Health research notice", "html_url": owner.base + "/notice-b",
                         "publication_date": datetime.now(timezone.utc).date().isoformat(), "abstract": "Unrelated research."}]}).encode()
                elif self.path == "/rss-mixed":
                    items = "".join(f'<item><title>{title}</title><link>{owner.base}/article-{i}</link>'
                        f'<pubDate>{format_datetime(datetime.now(timezone.utc))}</pubDate>'
                        '<description>Short summary</description><content:encoded><![CDATA[<p>Extended source text.</p>]]></content:encoded></item>'
                        for i, title in enumerate(("Robot deployment", "Muse AI feedback", "Museum weather forecast")))
                    body = ('<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>' + items + '</channel></rss>').encode()
                elif self.path == "/broken":
                    body = b"<html>not a feed</html>"
                elif self.path == "/page":
                    body = b"<html><head><title>Launch report</title></head><body><nav>Menu</nav><article>A successful launch.</article></body></html>"
                elif self.path == "/atom":
                    body = (f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Robot trial</title><link href="{owner.base}/article-b"/><updated>{datetime.now(timezone.utc).isoformat()}</updated><summary>Factory deployment</summary></entry></feed>').encode()
                else:
                    body = (f'<rss version="2.0"><channel><item><title>Launch</title><link>{owner.base}/article-a</link><pubDate>{format_datetime(datetime.now(timezone.utc))}</pubDate><description>New launch milestone</description></item></channel></rss>').encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html" if self.path == "/page" else "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def seed(self, task="test", paths=("/rss",), interval=0, budget=12, topics=None):
        config = {"id": task, "schedule_format": "cron", "topic_ids": topics or ["space-race"],
                  "execution": {"command": [PYTHON, "-m", "collectors.news"], "working_dir": str(REPO),
                                "timeout_seconds": 30, "lock_group": "web-fetch"},
                  "collector": {"sources": [{"name": path.strip("/"), "type": "page" if path == "/page" else "federal_register" if path == "/federal" else "rss", "url": self.base + path} for path in paths],
                                "request_policy": {"min_interval_seconds_per_host": interval, "min_interval_seconds_global": 0, "max_requests_per_run": budget}},
                  "options": {"max_items_per_run": 10, "lookback_hours": 30}}
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("""INSERT INTO tasks(id,name,task_type,scheduler_engine,enabled,schedule,timezone,config_json,created_at,updated_at)
                                VALUES (?,?,'test','news-claw',1,'15 7 * * *','Asia/Shanghai',?,'2026-10-10','2026-10-10')""",
                               (task, task, json.dumps(config)))

    def command(self, *args):
        result = subprocess.run([BINARY, *args, "--root", str(self.root), "--db", str(self.db)], capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def collect(self, task="test"):
        run = json.loads(self.command("enqueue", "--task", task))["run_id"]
        self.command("serve", "--once")
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.row_factory = sqlite3.Row
            row = dict(connection.execute("SELECT * FROM task_runs WHERE id=?", (run,)).fetchone())
        row["log"] = (self.root / row["log_path"]).read_text()
        return row

    def test_archive_deduplication_cache_and_topic_merge(self):
        self.seed(paths=("/rss", "/atom", "/page"))
        first = self.collect()
        self.assertEqual(first["status"], "succeeded", first["log"])
        self.assertEqual((first["items_seen"], first["items_new"]), (3, 3))
        with closing(sqlite3.connect(self.db)) as connection, connection:
            documents = connection.execute("SELECT raw_path,metadata_path,normalized_path FROM documents").fetchall()
        for paths in documents:
            for path in paths:
                self.assertTrue((self.root / path).is_file(), path)
        self.seed(task="second", paths=("/rss", "/atom", "/page"), topics=["physical-ai"])
        requests_before = len(self.requests)
        second = self.collect("second")
        self.assertEqual(second["status"], "succeeded", second["log"])
        self.assertEqual(second["items_new"], 0)
        self.assertEqual(len(self.requests), requests_before, "cached run unexpectedly accessed network")
        with closing(sqlite3.connect(self.db)) as connection, connection:
            links = connection.execute("SELECT topic_links_json FROM documents").fetchall()
        for (value,) in links:
            self.assertEqual({link["topic_id"] for link in json.loads(value)}, {"space-race", "physical-ai"})

    def test_circuit_survives_restart_and_does_not_retry(self):
        self.seed(paths=("/denied",))
        first = self.collect()
        self.assertEqual(first["status"], "failed", first["log"])
        self.assertEqual(sum(path == "/denied" for path, _ in self.requests), 1)
        details = json.loads(first["metadata_json"])["result"]["failure_details"]
        self.assertEqual(details, [{"category": "http_rate_limited", "url": self.base + "/denied", "http_status": 429}])
        state = next(value for path in (self.root / "data/runs/request-policy").glob("*.json")
                     if (value := json.loads(path.read_text())).get("blocked"))
        self.assertGreater(state["not_before"], time.time() + 50, "Retry-After deadline not persisted")
        before = len(self.requests)
        second = self.collect()
        self.assertEqual(second["status"], "failed", second["log"])
        self.assertEqual(len(self.requests), before, "blocked source retried after restart")

    def test_robots_denial_preserves_endpoint_and_reason(self):
        self.robots = b"User-agent: *\nDisallow: /rss\n"
        self.seed()
        result = self.collect()
        self.assertEqual(result["status"], "failed")
        self.assertIn("Forbidden by robots.txt", result["error"])
        self.assertIn(self.base + "/rss", result["error"])
        self.assertEqual([path for path, _ in self.requests], ["/robots.txt"])
        details = json.loads(result["metadata_json"])["result"]["failure_details"]
        self.assertEqual(details, [{"category": "robots_denied", "url": self.base + "/rss",
                                   "http_status": None, "robots_url": self.base + "/robots.txt",
                                   "blocked_before_download": True}])

    def test_http_access_denial_is_not_reported_as_robots_or_rate_limit(self):
        self.seed(paths=("/forbidden",))
        result = self.collect()
        self.assertEqual(result["status"], "failed", result["log"])
        details = json.loads(result["metadata_json"])["result"]["failure_details"]
        self.assertEqual(details, [{"category": "http_access_denied", "url": self.base + "/forbidden", "http_status": 403}])
        self.assertEqual(sum(path == "/forbidden" for path, _ in self.requests), 1)

    def set_robots_override(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            config = json.loads(db.execute("SELECT config_json FROM tasks WHERE id='test'").fetchone()[0])
            config["collector"]["sources"][0]["obey_robots_txt"] = False
            db.execute("UPDATE tasks SET config_json=? WHERE id='test'", (json.dumps(config),))

    def test_feed_override_does_not_disable_robots_for_other_sources(self):
        self.robots = b"User-agent: *\nDisallow: /rss\n"
        self.seed(paths=("/rss", "/rss-other"))
        self.set_robots_override()
        result = self.collect()
        self.assertEqual(result["status"], "failed", result["log"])
        self.assertEqual(result["items_new"], 1)
        self.assertEqual(sorted(path for path, _ in self.requests), ["/robots.txt", "/rss"])
        metadata = json.loads(result["metadata_json"])["result"]
        self.assertEqual(metadata["robots_override_urls"], [self.base + "/rss"])
        self.assertEqual(metadata["failure_details"][0]["url"], self.base + "/rss-other")

    def test_feed_override_does_not_follow_redirect_to_disallowed_url(self):
        self.robots = b"User-agent: *\nDisallow: /rss\n"
        self.seed(paths=("/rss-redirect",))
        self.set_robots_override()
        result = self.collect()
        self.assertEqual(result["status"], "failed", result["log"])
        self.assertEqual(sorted(path for path, _ in self.requests), ["/robots.txt", "/rss-redirect"])
        metadata = json.loads(result["metadata_json"])["result"]
        self.assertEqual(metadata["robots_override_urls"], [self.base + "/rss-redirect"])
        self.assertEqual(metadata["failure_details"][0]["category"], "robots_denied")
        self.assertEqual(metadata["failure_details"][0]["url"], self.base + "/rss-target")

    def test_feed_override_retains_http_rate_limit_circuit(self):
        self.seed(paths=("/denied",))
        self.set_robots_override()
        first = self.collect()
        self.assertEqual(first["status"], "failed", first["log"])
        self.assertEqual([path for path, _ in self.requests], ["/denied"])
        details = json.loads(first["metadata_json"])["result"]["failure_details"]
        self.assertEqual(details[0]["category"], "http_rate_limited")
        second = self.collect()
        self.assertEqual(second["status"], "failed", second["log"])
        self.assertEqual([path for path, _ in self.requests], ["/denied"])

    def test_federal_register_notices_are_filtered_and_archived(self):
        self.seed(paths=("/federal",))
        with closing(sqlite3.connect(self.db)) as db, db:
            config = json.loads(db.execute("SELECT config_json FROM tasks WHERE id='test'").fetchone()[0])
            config["collector"]["sources"][0]["include_keywords"] = ["export"]
            db.execute("UPDATE tasks SET config_json=? WHERE id='test'", (json.dumps(config),))
        result = self.collect()
        self.assertEqual(result["status"], "succeeded", result["log"])
        self.assertEqual((result["items_seen"], result["items_new"]), (2, 1))
        with closing(sqlite3.connect(self.db)) as db:
            title, raw, normalized = db.execute("SELECT title,raw_path,normalized_path FROM documents").fetchone()
        self.assertIn("China semiconductor", title)
        self.assertTrue(raw.endswith(".json"))
        self.assertEqual(json.loads((self.root / normalized).read_text())["record_type"], "regulatory_notice")

    def test_rss_keyword_boundaries_content_and_source_topics(self):
        self.seed(paths=("/rss-mixed",), topics=["physical-ai", "space-race"])
        with closing(sqlite3.connect(self.db)) as db, db:
            config = json.loads(db.execute("SELECT config_json FROM tasks WHERE id='test'").fetchone()[0])
            config["collector"]["sources"][0].update(include_keywords=["robot", "muse"], topic_ids=["physical-ai"])
            db.execute("UPDATE tasks SET config_json=? WHERE id='test'", (json.dumps(config),))
        result = self.collect()
        self.assertEqual(result["status"], "succeeded", result["log"])
        self.assertEqual((result["items_seen"], result["items_new"]), (3, 2))
        with closing(sqlite3.connect(self.db)) as db:
            for normalized, links in db.execute("SELECT normalized_path,topic_links_json FROM documents"):
                self.assertIn("Extended source text", json.loads((self.root / normalized).read_text())["text"])
                self.assertEqual({item["topic_id"] for item in json.loads(links)}, {"physical-ai"})

    def test_shared_interval_across_tasks(self):
        self.seed(task="one", paths=("/rss",), interval=0.25)
        self.seed(task="two", paths=("/page",), interval=0.25)
        self.assertEqual(self.collect("one")["status"], "succeeded")
        self.assertEqual(self.collect("two")["status"], "succeeded")
        times = [timestamp for _, timestamp in self.requests]
        self.assertGreaterEqual(len(times), 3)
        self.assertTrue(all(b - a >= 0.23 for a, b in zip(times, times[1:])), times)

    def test_global_interval_survives_switching_hosts_and_tasks(self):
        self.seed(task="one", paths=("/rss",))
        self.seed(task="two", paths=("/page",))
        with closing(sqlite3.connect(self.db)) as db, db:
            for task in ("one", "two"):
                config = json.loads(db.execute("SELECT config_json FROM tasks WHERE id=?", (task,)).fetchone()[0])
                config["collector"]["request_policy"]["min_interval_seconds_global"] = 0.25
                if task == "two":
                    config["collector"]["sources"][0]["url"] = self.base.replace("127.0.0.1", "localhost") + "/page"
                db.execute("UPDATE tasks SET config_json=? WHERE id=?", (json.dumps(config), task))
        self.assertEqual(self.collect("one")["status"], "succeeded")
        self.assertEqual(self.collect("two")["status"], "succeeded")
        times = [timestamp for _, timestamp in self.requests]
        self.assertEqual(len(times), 4)
        self.assertTrue(all(b - a >= 0.23 for a, b in zip(times, times[1:])), times)

    def test_budget_and_invalid_feed_fail_the_run(self):
        self.seed(task="budget", paths=("/rss", "/page"), budget=1)
        result = self.collect("budget")
        self.assertEqual(result["status"], "failed", result["log"])
        self.assertLessEqual(len(self.requests), 1)
        self.seed(task="invalid", paths=("/broken",))
        result = self.collect("invalid")
        self.assertEqual(result["status"], "failed", result["log"])

    def test_legacy_service_bridge_uses_unit_result(self):
        self.seed()
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        controller = fake_bin / "systemctl"
        service_input = self.root / 'data/runs/service-inputs/quant-blog-daily.service.json'
        controller.write_text(f"#!{PYTHON}\nimport sys\nif '--property=Environment' in sys.argv:\n print('NEWS_CLAW_TASK_CONFIG_PATH={service_input}')\nelif sys.argv[1] == 'show':\n print('ActiveState=inactive\\nResult=success\\nExecMainStatus=0')\n")
        controller.chmod(0o755)
        journal = fake_bin / "journalctl"
        outcome = {'status': 'awaiting_editor_approval', 'day': '2026-10-10'}
        journal.write_text(f"#!{PYTHON}\nprint('mock legacy service journal')\nprint({json.dumps(outcome)!r})\n")
        journal.chmod(0o755)
        with closing(sqlite3.connect(self.db)) as db, db:
            task = json.loads(db.execute("SELECT config_json FROM tasks WHERE id='test'").fetchone()[0])
            task['execution'].update(command=[PYTHON, '-m', 'collectors.legacy_service', '--unit', 'quant-blog-daily.service'],
                                     systemd_unit='quant-blog-daily.service', env={'PATH': str(fake_bin) + ':' + os.environ['PATH']})
            task['workflow'] = {'codex': {'model': 'gpt-6.1-sol', 'reasoning_effort': 'medium',
                                        'service_tier': 'default', 'permissions': 'full'}}
            db.execute("UPDATE tasks SET config_json=? WHERE id='test'", (json.dumps(task),))
        result = self.collect()
        self.assertEqual(result['status'], 'succeeded', result['log'])
        self.assertEqual(json.loads(service_input.read_text()), task)
        self.assertEqual(service_input.stat().st_mode & 0o777, 0o600)
        self.assertIn('mock legacy service journal', result['log'])
        self.assertEqual(json.loads(result['metadata_json'])['result']['business_status'], 'awaiting_editor_approval')
        outcome['status'] = 'model_provider_blocked'
        journal.write_text(f"#!{PYTHON}\nprint({json.dumps(outcome)!r})\n")
        blocked = self.collect()
        self.assertEqual(blocked['status'], 'failed', blocked['log'])
        self.assertEqual(json.loads(blocked['metadata_json'])['result']['business_status'], 'model_provider_blocked')


class SharedCircuitTest(unittest.IsolatedAsyncioTestCase):
    def test_robots_override_requires_a_boolean_and_feed_type(self):
        from collectors.news import validate
        task = {"collector": {"sources": [{"type": "rss", "url": "https://example.com/feed",
                                           "obey_robots_txt": "false"}]}}
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            validate(task)
        task["collector"]["sources"][0].update(type="page", obey_robots_txt=False)
        with self.assertRaisesRegex(ValueError, "only for RSS/Atom"):
            validate(task)

    async def test_scrapy_obeys_legacy_google_circuit(self):
        import scrapy
        from scrapy.exceptions import IgnoreRequest
        from collectors.news import RequestPolicy
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            circuit = root / 'old-circuit.json'
            circuit.write_text('{"open": true, "reason": "rate_limited"}')
            spider = Mock()
            spider.root = root
            spider.task = {'collector': {'request_policy': {'shared_circuit_paths': [str(circuit)]}}}
            spider.requests_made, spider.request_budget = 0, 12
            with self.assertRaises(IgnoreRequest):
                await RequestPolicy(Mock()).process_request(scrapy.Request('https://news.google.com/rss'), spider)
            self.assertEqual(spider.requests_made, 0)


if __name__ == "__main__":
    unittest.main()
